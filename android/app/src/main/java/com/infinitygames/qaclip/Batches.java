package com.infinitygames.qaclip;

import android.content.Context;
import android.content.Intent;
import android.content.ClipData;
import android.net.Uri;
import org.json.JSONArray;
import org.json.JSONObject;
import java.io.File;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.text.SimpleDateFormat;
import java.util.Arrays;
import java.util.Date;
import java.util.Locale;
import java.util.UUID;
import java.util.List;

/** Phone-only sessions live outside the Mac outbox and are never automatically uploaded or pruned. */
final class Batches {
    static boolean standalone(Context c) { return c.getSharedPreferences("qaclip", 0).getBoolean("standalone", false); }
    static File root(Context c) { File dir = new File(c.getExternalFilesDir(null), "batches"); dir.mkdirs(); return dir; }
    static String date(long millis) { return new SimpleDateFormat("yyyy-MM-dd HH:mm", Locale.US).format(new Date(millis)); }

    static File create(Context c, String game) throws Exception {
        String id = UUID.randomUUID().toString();
        File dir = new File(root(c), id);
        if (!dir.mkdirs()) throw new IOException("Could not create a saved batch");
        JSONObject info = new JSONObject().put("id", id).put("game", game).put("createdAt", date(System.currentTimeMillis()));
        Files.write(new File(dir, "batch.json").toPath(), info.toString().getBytes(StandardCharsets.UTF_8));
        return dir;
    }

    static JSONObject info(File dir) throws Exception {
        return new JSONObject(new String(Files.readAllBytes(new File(dir, "batch.json").toPath()), StandardCharsets.UTF_8));
    }

    static File[] clips(File dir) {
        File[] files = dir.listFiles((parent, name) -> name.endsWith(".mp4"));
        if (files == null) return new File[0];
        Arrays.sort(files); return files;
    }

    static File[] saved(Context c) {
        File[] dirs = root(c).listFiles(file -> file.isDirectory() && new File(file, "batch.json").isFile() && clips(file).length > 0);
        if (dirs == null) return new File[0];
        Arrays.sort(dirs, (a, b) -> Long.compare(b.lastModified(), a.lastModified())); return dirs;
    }

    static String label(File dir) {
        try {
            JSONObject info = info(dir);
            return info.optString("game", "").isEmpty() ? "Playtest session" : info.getString("game");
        } catch (Exception e) { return "Playtest session"; }
    }

    static File export(Context c, File dir) throws Exception {
        return export(c, dir, 0);
    }

    static List<List<File>> parts(File dir) throws IOException { return BatchArchive.parts(Arrays.asList(clips(dir))); }

    static File export(Context c, File dir, int part) throws Exception {
        JSONObject info = info(dir);
        List<List<File>> parts = parts(dir);
        File[] clips = parts.get(part).toArray(new File[0]);
        JSONArray entries = new JSONArray();
        // Explicit allowlist: pairing identities, phone keys and local paths never travel in an archive.
        String[] fields = {"appLabel", "app", "appVersion", "pressedAt", "pressedAtSecond", "clipSeconds", "lookbackSeconds", "voice", "size", "device", "android"};
        for (int i = 0; i < clips.length; i++) {
            File sidecar = new File(dir, clips[i].getName().replace(".mp4", ".json"));
            JSONObject original = sidecar.isFile() ? new JSONObject(new String(Files.readAllBytes(sidecar.toPath()), StandardCharsets.UTF_8)) : new JSONObject();
            JSONObject entry = new JSONObject().put("file", BatchArchive.clipName(i));
            String game = original.optString("game", "").trim();
            if (game.isEmpty()) game = original.optString("appLabel", info.optString("game", "Unknown game")).trim();
            if (game.isEmpty()) game = "Unknown game";
            entry.put("game", game.length() > 80 ? game.substring(0, 80) : game);
            for (String field : fields) if (original.has(field) && !original.isNull(field)) entry.put(field, original.get(field));
            entries.put(entry);
        }
        JSONObject manifest = new JSONObject().put("format", "playtest-demon-batch").put("version", 1)
                .put("batchId", info.getString("id")).put("createdAt", info.getString("createdAt")).put("clips", entries)
                .put("part", part + 1).put("parts", parts.size());
        File shareDir = new File(c.getCacheDir(), "shared-batches"); shareDir.mkdirs();
        String name = info.getString("id") + "-part-" + (part + 1);
        File output = new File(shareDir, name + ".zip");
        File temp = new File(shareDir, name + ".part");
        BatchArchive.write(temp, Arrays.asList(clips), manifest.toString());
        Files.move(temp.toPath(), output.toPath(), java.nio.file.StandardCopyOption.REPLACE_EXISTING);
        return output;
    }

    static Intent shareIntent(Context c, File batch, File file) {
        Uri uri = new Uri.Builder().scheme("content").authority(c.getPackageName() + ".batches").appendPath(file.getName()).build();
        Intent send = new Intent(Intent.ACTION_SEND).setType("application/zip")
            .putExtra(Intent.EXTRA_STREAM, uri).putExtra(Intent.EXTRA_SUBJECT, label(batch) + " playtest batch")
            .putExtra(Intent.EXTRA_TEXT, "Import this ZIP in Playtest Demon on your Mac: Import batch. It contains the recordings and spoken feedback.")
            .addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION);
        send.setClipData(ClipData.newRawUri("Playtest recordings", uri));
        return send;
    }
}

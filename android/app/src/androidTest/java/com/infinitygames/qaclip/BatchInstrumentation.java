package com.infinitygames.qaclip;

import android.app.Activity;
import android.app.Instrumentation;
import android.content.Context;
import android.content.Intent;
import android.net.Uri;
import android.os.Bundle;
import org.json.JSONObject;
import java.io.File;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.util.Arrays;
import java.util.zip.ZipFile;

/** Device checks on a disposable emulator. No capture consent, provider usage or real recordings. */
public final class BatchInstrumentation extends Instrumentation {
    @Override public void onCreate(Bundle arguments) { super.onCreate(arguments); start(); }
    private static void check(boolean value, String message) { if (!value) throw new AssertionError(message); }
    @Override public void onStart() {
        Bundle result = new Bundle();
        try {
            Context c = getTargetContext();
            c.getSharedPreferences("qaclip", 0).edit().putBoolean("standalone", true).putString("macCode", "").remove("macId").commit();
            File batch = Batches.create(c, "Synthetic Racing");
            File video = new File(batch, "fixture.mp4");
            try (InputStream in = getContext().getAssets().open("batch-fixture.mp4")) {
                Files.copy(in, video.toPath());
            }
            JSONObject meta = new JSONObject().put("game", "Synthetic Racing").put("pressedAtSecond", .5)
                .put("lookbackSeconds", 10).put("voice", true).put("appVersion", "test-build")
                .put("receiverId", "never-share-this").put("receiverCode", "never-share-this").put("key", "never-share-this");
            Files.write(new File(batch, "fixture.json").toPath(), meta.toString().getBytes(StandardCharsets.UTF_8));
            check(!Arrays.asList(Clips.waiting(c)).contains(video), "A local batch entered the Mac outbox");
            Uploader uploader = Uploader.get(c); uploader.kick();
            Thread.sleep(300);
            check(video.isFile() && !uploader.ok, "Standalone clip was uploaded");
            // Explicit pairing must never adopt or relabel a standalone recording.
            String originalMeta = new String(Files.readAllBytes(new File(batch, "fixture.json").toPath()), StandardCharsets.UTF_8);
            uploader.chooseMac("ABCD-1234");
            check(originalMeta.equals(new String(Files.readAllBytes(new File(batch, "fixture.json").toPath()), StandardCharsets.UTF_8)), "Pairing changed a local batch destination");
            File zip = Batches.export(c, batch);
            try (ZipFile archive = new ZipFile(zip)) {
                JSONObject manifest = new JSONObject(new String(archive.getInputStream(archive.getEntry("manifest.json")).readAllBytes(), StandardCharsets.UTF_8));
                check(manifest.getString("format").equals("playtest-demon-batch"), "Wrong format");
                JSONObject clip = manifest.getJSONArray("clips").getJSONObject(0);
                check(clip.getString("game").equals("Synthetic Racing") && clip.getDouble("pressedAtSecond") == .5, "Metadata lost");
                check(!clip.has("receiverId") && !clip.has("receiverCode") && !clip.has("key"), "Pairing information leaked");
                check(archive.size() == 2, "Unexpected exported files");
            }
            Intent send = Batches.shareIntent(c, batch, zip);
            Uri uri = send.getParcelableExtra(Intent.EXTRA_STREAM);
            check("application/zip".equals(send.getType()) && "content".equals(uri.getScheme()), "Unsafe share type or URI");
            check((send.getFlags() & Intent.FLAG_GRANT_READ_URI_PERMISSION) != 0 && send.getClipData() != null, "Missing share grant");
            try (InputStream in = c.getContentResolver().openInputStream(uri)) { check(in.read() == 'P', "Shared ZIP not readable"); }
            try { c.getContentResolver().openOutputStream(uri); throw new AssertionError("Provider allowed writes"); }
            catch (java.io.FileNotFoundException expected) { }
            Uri escape = uri.buildUpon().path("/../shared-preferences.xml").build();
            try { c.getContentResolver().openInputStream(escape); throw new AssertionError("Provider allowed traversal"); }
            catch (java.io.FileNotFoundException expected) { }
            check(video.isFile() && Batches.saved(c).length > 0, "Sharing removed original recordings");
            // Keep the synthetic export available for a real desktop import check.
            Files.copy(zip.toPath(), new File(c.getFilesDir(), "batch-device-test.zip").toPath(), java.nio.file.StandardCopyOption.REPLACE_EXISTING);
            c.getSharedPreferences("qaclip", 0).edit().remove("macCode").remove("macId").commit();
            result.putString("stream", "BATCH_DEVICE_TESTS_OK: offline storage, routing isolation, portable ZIP and read-only share URI\n");
            finish(Activity.RESULT_OK, result);
        } catch (Throwable error) {
            result.putString("stream", "BATCH_DEVICE_TESTS_FAILED: " + android.util.Log.getStackTraceString(error));
            finish(Activity.RESULT_CANCELED, result);
        }
    }
}

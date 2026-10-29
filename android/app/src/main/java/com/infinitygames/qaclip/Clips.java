package com.infinitygames.qaclip;

import android.content.Context;
import android.content.pm.PackageInfo;
import android.content.pm.PackageManager;
import android.os.Build;
import android.util.Log;

import org.json.JSONObject;

import java.io.File;
import java.io.FileOutputStream;
import java.nio.charset.StandardCharsets;
import java.text.SimpleDateFormat;
import java.util.Arrays;
import java.util.Date;
import java.util.Locale;

/** Where clips wait on the phone (outbox), and the little JSON that rides along with each one. */
final class Clips {
    static File outbox(Context c) { return dir(c, "outbox"); }

    static File sent(Context c) { return dir(c, "sent"); }

    private static File dir(Context c, String name) {
        File d = new File(c.getExternalFilesDir(null), name);
        d.mkdirs();
        return d;
    }

    static File[] waiting(Context c) {
        File[] f = outbox(c).listFiles((d, n) -> n.endsWith(".mp4"));
        if (f == null) return new File[0];
        Arrays.sort(f);
        return f;
    }

    static void writeMeta(Context c, Recorder.Clip clip, String app, String game, long wallMs, Recorder r, boolean standalone) {
        try {
            JSONObject j = new JSONObject();
            PackageManager pm = c.getPackageManager();
            String label = app, version = null;
            if (app != null) {
                try {
                    PackageInfo pi = pm.getPackageInfo(app, 0);
                    label = pi.applicationInfo.loadLabel(pm).toString();
                    version = pi.versionName + " (" + pi.getLongVersionCode() + ")";
                } catch (Exception ignored) { }
            }
            SimpleDateFormat iso = new SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ssXXX", Locale.US);
            j.put("game", game);
            if (!standalone) {
                j.put("receiverCode", Uploader.get(c).macCode());
                j.put("receiverId", Uploader.get(c).macId());
            }
            j.put("lookbackSeconds", r.lookbackUs / 1_000_000);
            j.put("appLabel", label != null ? label : "Unknown app");
            j.put("app", app);
            j.put("appVersion", version);
            j.put("pressedAt", iso.format(new Date(wallMs)));
            j.put("pressedAtSecond", Math.round(clip.preUs / 100_000.0) / 10.0);
            j.put("clipSeconds", Math.round(clip.durUs / 100_000.0) / 10.0);
            j.put("voice", clip.audio);
            j.put("size", r.w + "x" + r.h);
            j.put("device", Build.MANUFACTURER + " " + Build.MODEL);
            j.put("android", Build.VERSION.RELEASE);
            File f = new File(clip.file.getParent(), clip.file.getName().replace(".mp4", ".json"));
            try (FileOutputStream o = new FileOutputStream(f)) {
                o.write(j.toString(1).getBytes(StandardCharsets.UTF_8));
            }
        } catch (Exception e) {
            Log.w(Recorder.TAG, "meta: " + e);
        }
    }

    /** Keeps the newest n clips in sent/, as a safety copy after the Mac confirmed it has them. */
    static void prune(File dir, int keep) {
        File[] f = dir.listFiles((d, n) -> n.endsWith(".mp4"));
        if (f == null || f.length <= keep) return;
        Arrays.sort(f);
        for (int i = 0; i < f.length - keep; i++) {
            f[i].delete();
            new File(dir, f[i].getName().replace(".mp4", ".json")).delete();
        }
    }
}

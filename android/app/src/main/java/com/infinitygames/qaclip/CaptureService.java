package com.infinitygames.qaclip;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.app.Service;
import android.content.Intent;
import android.content.pm.ServiceInfo;
import android.graphics.Rect;
import android.media.projection.MediaProjection;
import android.media.projection.MediaProjectionManager;
import android.os.Build;
import android.os.Handler;
import android.os.IBinder;
import android.os.Looper;
import android.os.SystemClock;
import android.util.DisplayMetrics;
import android.util.Log;
import android.view.WindowManager;
import android.widget.Toast;

import java.io.File;
import java.text.SimpleDateFormat;
import java.util.Date;
import java.util.Locale;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

/** One QA session: holds the screen capture, and turns volume presses into clips. */
public final class CaptureService extends Service {
    static final String START = "start", STOP = "stop";
    static final long MAX_CLIP_MS = 180_000;
    static volatile CaptureService I;
    static volatile boolean finalizing;

    private final Handler main = new Handler(Looper.getMainLooper());
    private ExecutorService work;
    private MediaProjection mp;
    private Recorder rec;
    private boolean ending, clipping;
    private long sessionStart, clipStart, clipWall;
    private String clipApp, clipGame;
    private boolean standalone;
    private File batch;

    boolean clipping() { return clipping; }

    @Override public IBinder onBind(Intent i) { return null; }

    @Override
    public int onStartCommand(Intent in, int flags, int id) {
        String a = in == null ? null : in.getAction();
        if (STOP.equals(a)) {
            endSession();
            return START_NOT_STICKY;
        }
        if (!START.equals(a) || rec != null || finalizing) return START_NOT_STICKY;

        boolean voice = in.getBooleanExtra("voice", false);
        try {
            startForeground(1, note(), ServiceInfo.FOREGROUND_SERVICE_TYPE_MEDIA_PROJECTION
                    | (voice ? ServiceInfo.FOREGROUND_SERVICE_TYPE_MICROPHONE : 0));
        } catch (Exception e) {
            Log.w(Recorder.TAG, "no mic for this session: " + e);
            voice = false;
            startForeground(1, note(), ServiceInfo.FOREGROUND_SERVICE_TYPE_MEDIA_PROJECTION);
        }
        Intent data = Build.VERSION.SDK_INT >= 33
                ? in.getParcelableExtra("data", Intent.class)
                : in.getParcelableExtra("data");
        MediaProjectionManager pm = getSystemService(MediaProjectionManager.class);
        mp = data == null ? null : pm.getMediaProjection(in.getIntExtra("code", 0), data);
        if (mp == null) {
            fail("Screen capture was not allowed");
            return START_NOT_STICKY;
        }
        mp.registerCallback(new MediaProjection.Callback() {
            @Override public void onStop() { main.post(CaptureService.this::endSession); }
        }, main);

        int[] s = captureSize();
        rec = new Recorder(mp, s[0], s[1], s[2], voice, getSharedPreferences("qaclip", 0).getInt("lookback", 10));
        try {
            standalone = Batches.standalone(this);
            if (standalone) batch = Batches.create(this, Games.selected(this));
            rec.start();
        } catch (Exception e) {
            Log.w(Recorder.TAG, "capture start: " + e);
            rec = null;
            fail("Could not start screen capture");
            return START_NOT_STICKY;
        }
        work = Executors.newSingleThreadExecutor();
        sessionStart = SystemClock.elapsedRealtime();
        I = this;
        Uploader.get(this).kick();
        return START_NOT_STICKY;
    }

    // ---- the three buttons ----

    void volUp() {
        if (clipping) save();
        else begin();
    }

    void volDown() {
        if (clipping) discard();
    }

    private void begin() {
        final Recorder r = rec;
        if (r == null) return;
        if (standalone && Batches.clips(batch).length >= BatchArchive.MAX_CLIPS) {
            Toast.makeText(this, "Batch full. Stop this session and start a new one.", Toast.LENGTH_LONG).show(); return;
        }
        clipping = true;
        clipStart = SystemClock.elapsedRealtime();
        clipWall = System.currentTimeMillis();
        clipApp = KeyService.foregroundApp();
        clipGame = Games.selected(this);
        final File dir = standalone ? batch : Clips.outbox(this);
        final String name = new SimpleDateFormat("yyyyMMdd-HHmmss", Locale.US).format(new Date(clipWall))
                + (standalone ? "-" + java.util.UUID.randomUUID().toString().substring(0, 8) : "");
        Feedback.buzz(this, Feedback.START);
        KeyService.pill(label(), Feedback.RED);
        refreshNote();
        main.postDelayed(tick, 1000);
        work.execute(() -> {
            boolean full = standalone && Batches.clips(batch).length >= BatchArchive.MAX_CLIPS;
            if (full || !r.startClip(dir, name)) main.post(() -> {
                if (!clipping) return;
                clipping = false;
                main.removeCallbacks(tick);
                KeyService.flash(full ? "Batch full · start a new session" : "No video yet", Feedback.GREY);
                refreshNote();
            });
        });
    }

    private void save() {
        final Recorder r = rec;
        if (!clipping || r == null) return;
        clipping = false;
        main.removeCallbacks(tick);
        final String app = clipApp, game = clipGame;
        final long wall = clipWall;
        Feedback.buzz(this, Feedback.SAVE);
        KeyService.flash("Saved", Feedback.GREEN);
        refreshNote();
        work.execute(() -> {
            Recorder.Clip c = r.stopClip(true);
            if (c == null) {
                main.post(() -> KeyService.flash("Clip failed", Feedback.GREY));
                return;
            }
            Clips.writeMeta(this, c, app, game, wall, r, standalone);
            if (!standalone) Uploader.get(this).kick();
        });
    }

    private void discard() {
        final Recorder r = rec;
        if (!clipping || r == null) return;
        clipping = false;
        main.removeCallbacks(tick);
        Feedback.buzz(this, Feedback.DISCARD);
        KeyService.flash("Thrown away", Feedback.GREY);
        refreshNote();
        work.execute(() -> r.stopClip(false));
    }

    /** Clip length so far: the configured pre-roll plus the time since the press. */
    private String label() {
        long now = SystemClock.elapsedRealtime();
        long pre = Math.min(rec.lookbackUs / 1000, clipStart - sessionStart);
        long s = (pre + now - clipStart) / 1000;
        return String.format(Locale.US, "● REC %d:%02d", s / 60, s % 60);
    }

    private final Runnable tick = new Runnable() {
        @Override public void run() {
            if (!clipping) return;
            if (SystemClock.elapsedRealtime() - clipStart >= MAX_CLIP_MS) {
                save();
                return;
            }
            KeyService.pill(label(), Feedback.RED);
            main.postDelayed(this, 1000);
        }
    };

    // ---- session ----

    void endSession() {
        if (ending) return;
        ending = true;
        if (clipping) save(); // never lose what the tester was recording
        I = null;
        final Recorder r = rec;
        final MediaProjection m = mp;
        rec = null;
        mp = null;
        if (work != null) {
            finalizing = true;
            work.execute(() -> {
                try {
                    if (r != null) r.stop();
                    if (m != null) m.stop();
                } finally { finalizing = false; }
            });
            work.shutdown();
        } else if (m != null) {
            m.stop();
        }
        KeyService.hidePill();
        stopForeground(STOP_FOREGROUND_REMOVE);
        stopSelf();
    }

    private void fail(String msg) {
        Toast.makeText(this, msg, Toast.LENGTH_LONG).show();
        endSession();
    }

    private int[] captureSize() {
        WindowManager wm = getSystemService(WindowManager.class);
        int sw, sh;
        if (Build.VERSION.SDK_INT >= 30) {
            Rect b = wm.getMaximumWindowMetrics().getBounds();
            sw = b.width();
            sh = b.height();
        } else {
            DisplayMetrics m = new DisplayMetrics();
            wm.getDefaultDisplay().getRealMetrics(m);
            sw = m.widthPixels;
            sh = m.heightPixels;
        }
        float k = Math.min(1f, 720f / Math.min(sw, sh));
        return new int[] { round16(sw * k), round16(sh * k), getResources().getDisplayMetrics().densityDpi };
    }

    private static int round16(float v) { return Math.max(16, Math.round(v / 16f) * 16); }

    // ---- notification ----

    private void refreshNote() {
        if (ending) return;
        getSystemService(NotificationManager.class).notify(1, note());
    }

    private Notification note() {
        NotificationManager nm = getSystemService(NotificationManager.class);
        if (nm.getNotificationChannel("session") == null) {
            nm.createNotificationChannel(new NotificationChannel("session", "QA session", NotificationManager.IMPORTANCE_LOW));
        }
        PendingIntent open = PendingIntent.getActivity(this, 0,
                new Intent(this, MainActivity.class), PendingIntent.FLAG_IMMUTABLE);
        PendingIntent stop = PendingIntent.getService(this, 1,
                new Intent(this, CaptureService.class).setAction(STOP), PendingIntent.FLAG_IMMUTABLE);
        return new Notification.Builder(this, "session")
                .setSmallIcon(R.drawable.ic_note)
                .setContentTitle(clipping ? "Recording a clip" : "Playtest Demon session on")
                .setContentText(clipping ? "Vol + to save · Vol − to throw away" : "Vol + starts a clip with your lookback")
                .setContentIntent(open)
                .addAction(new Notification.Action.Builder(null, "Stop session", stop).build())
                .setOngoing(true)
                .build();
    }
}

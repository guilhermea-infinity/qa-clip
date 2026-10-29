package com.infinitygames.qaclip;

import android.content.Context;
import android.content.SharedPreferences;
import android.net.nsd.NsdManager;
import android.net.nsd.NsdServiceInfo;
import android.os.Build;
import android.provider.Settings;
import android.util.Log;

import org.json.JSONObject;
import org.json.JSONArray;

import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.FileInputStream;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.Inet4Address;
import java.net.InetAddress;
import java.net.URL;
import java.net.URLEncoder;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.security.SecureRandom;
import java.util.ArrayList;
import java.util.Collections;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Set;

/**
 * Sends clips only to the explicitly paired Mac. Bonjour/USB locate that same identity;
 * another computer is never a fallback, even if it previously approved this phone.
 * Clips stay in the outbox until the Mac confirms the byte count, so nothing is lost offline.
 */
final class Uploader {
    static final int PORT = 8799;
    private static final String TYPE = "_qaclip._tcp";
    private static Uploader I;

    static synchronized Uploader get(Context c) {
        if (I == null) I = new Uploader(c.getApplicationContext());
        return I;
    }

    volatile boolean ok;
    volatile String state = "Tap Mac to pair with your laptop";

    private final Context ctx;
    private final SharedPreferences sp;
    private final Object wake = new Object();
    private final Object routeLock = new Object();
    private final Set<String> found = Collections.synchronizedSet(new LinkedHashSet<>());
    private NsdManager nsd;

    private Uploader(Context c) {
        ctx = c;
        sp = c.getSharedPreferences("qaclip", 0);
        Thread t = new Thread(this::loop, "qaclip-upload");
        t.setDaemon(true);
        t.start();
    }

    int waiting() { return Clips.waiting(ctx).length; }

    void kick() {
        synchronized (wake) { wake.notifyAll(); }
    }

    private void loop() {
        while (true) {
            try {
                File[] clips = Clips.waiting(ctx);
                if (!Batches.standalone(ctx) && nsd == null) discover();
                Target mac = Batches.standalone(ctx) ? null : reach();
                if (mac != null) {
                    for (File f : clips) if (!send(mac, f)) break;
                    syncGames(mac);
                }
            } catch (Throwable t) {
                Log.w(Recorder.TAG, "upload: " + t);
            }
            synchronized (wake) {
                try { wake.wait(waiting() > 0 ? 3000 : 6000); } catch (InterruptedException ignored) { }
            }
        }
    }

    static final class Target {
        final String address, id;
        Target(String address, String id) { this.address = address; this.id = id; }
    }

    String macCode() { return sp.getString("macCode", ""); }
    String macId() { return sp.getString("macId", ""); }

    void chooseMac(String code) throws Exception {
        code = MacRoute.normalize(code);
        if (!MacRoute.validCode(code)) throw new IllegalArgumentException("Enter the 8-character code shown on your Mac");
        synchronized (routeLock) {
            // Only an explicit choice adopts old, unaddressed clips. Already addressed clips stay put.
            for (File mp4 : Clips.waiting(ctx)) {
                File js = new File(mp4.getParent(), mp4.getName().replace(".mp4", ".json"));
                if (!js.exists()) continue;
                JSONObject meta = new JSONObject(new String(Files.readAllBytes(js.toPath()), StandardCharsets.UTF_8));
                if (meta.optString("receiverCode").isEmpty() && meta.optString("receiverId").isEmpty()) {
                    meta.put("receiverCode", code);
                    saveMeta(js, meta.toString());
                }
            }
            if (!code.equals(macCode())) sp.edit().putString("macCode", code).remove("macId").remove("macName").remove("last").commit();
            ok = false; state = "Finding your Mac · " + code;
        }
        kick();
    }

    private Target reach() {
        MacRoute route = new MacRoute(macCode(), macId());
        if (!MacRoute.validCode(route.code)) { ok = false; state = "Tap Mac to pair with your laptop"; return null; }
        Set<String> tries = new LinkedHashSet<>();
        String last = sp.getString("last", null);
        if (last != null) tries.add(last);
        synchronized (found) { tries.addAll(found); }
        tries.add("127.0.0.1:" + PORT);
        String why = null;
        for (String address : tries) {
            // Discover identity WITHOUT sending the phone key, games or clips to an unrelated Mac.
            JSONObject identity = identity(address);
            if (identity == null || !route.accepts(identity.optString("id"))) continue;
            String id = identity.optString("id"), name = identity.optString("name", "Your Mac");
            synchronized (routeLock) {
                if (!route.code.equals(macCode()) || (!macId().isEmpty() && !macId().equals(id))) return null;
                sp.edit().putString("macId", id).putString("macName", name).commit();
            }
            Target target = new Target(address, id);
            JSONObject j = ping(target);
            if (j == null) continue;
            String st = j.optString("status");
            if ("approved".equals(st)) {
                synchronized (routeLock) {
                    if (!id.equals(macId())) return null;
                    state = name + " · " + route.code; ok = true;
                    if (!address.equals(last)) sp.edit().putString("last", address).apply();
                }
                return target;
            }
            why = "pending".equals(st) ? "Click Allow on " + name : name + " declined this phone";
        }
        ok = false;
        state = why != null ? why : sp.getString("macName", "Your Mac") + " offline · clips stay here";
        return null;
    }

    private JSONObject identity(String address) {
        HttpURLConnection c = null;
        try {
            c = (HttpURLConnection) new URL("http://" + address + "/identity").openConnection();
            c.setUseCaches(false); c.setConnectTimeout(1000); c.setReadTimeout(1500);
            if (c.getResponseCode() != 200) return null;
            return new JSONObject(read(c.getInputStream()));
        } catch (Exception e) { return null; }
        finally { if (c != null) c.disconnect(); }
    }

    private JSONObject ping(Target target) {
        HttpURLConnection c = null;
        try {
            c = open(target, "/ping");
            c.setConnectTimeout(1200);
            c.setReadTimeout(2500);
            if (c.getResponseCode() != 200) return null;
            return new JSONObject(read(c.getInputStream()));
        } catch (Exception e) {
            return null;
        } finally {
            if (c != null) c.disconnect();
        }
    }

    private void syncGames(Target target) {
        if (Batches.standalone(ctx) || !target.id.equals(macId())) return;
        HttpURLConnection c = null;
        try {
            Set<String> pending = Games.pending(ctx);
            // Bound requests even after a long offline session.
            Set<String> batch = new LinkedHashSet<>();
            for (String name : pending) { if (batch.size() == 100) break; batch.add(name); }
            c = open(target, "/games");
            c.setConnectTimeout(2000);
            c.setReadTimeout(3000);
            if (!batch.isEmpty()) {
                c.setRequestMethod("POST"); c.setDoOutput(true);
                byte[] body = new JSONObject().put("games", new JSONArray(batch)).toString().getBytes(StandardCharsets.UTF_8);
                c.setRequestProperty("Content-Type", "application/json");
                c.setFixedLengthStreamingMode(body.length);
                try (OutputStream out = c.getOutputStream()) { out.write(body); }
            }
            if (c.getResponseCode() == 200) {
                JSONArray names = new JSONObject(read(c.getInputStream())).optJSONArray("games");
                if (names != null) Games.received(ctx, names, batch);
            }
        } catch (Exception e) { Log.w(Recorder.TAG, "game sync: " + e); }
        finally { if (c != null) c.disconnect(); }
    }

    private void saveMeta(File file, String value) throws Exception {
        java.nio.file.Path temp = new File(file.getParent(), file.getName() + ".route.tmp").toPath();
        Files.write(temp, value.getBytes(StandardCharsets.UTF_8));
        try { Files.move(temp, file.toPath(), java.nio.file.StandardCopyOption.ATOMIC_MOVE, java.nio.file.StandardCopyOption.REPLACE_EXISTING); }
        catch (java.nio.file.AtomicMoveNotSupportedException e) { Files.move(temp, file.toPath(), java.nio.file.StandardCopyOption.REPLACE_EXISTING); }
    }

    private boolean send(Target target, File mp4) {
        File js = new File(mp4.getParent(), mp4.getName().replace(".mp4", ".json"));
        HttpURLConnection c = null;
        try {
            String meta;
            synchronized (routeLock) {
                if (Batches.standalone(ctx) || !target.id.equals(macId())) return false;
                if (!js.exists()) return true; // recorder has not finished writing metadata yet
                JSONObject j = new JSONObject(new String(Files.readAllBytes(js.toPath()), StandardCharsets.UTF_8));
                MacRoute route = new MacRoute(macCode(), target.id);
                if (!route.ownsClip(j.optString("receiverCode"), j.optString("receiverId"))) return true;
                j.put("receiverId", target.id);
                meta = j.toString();
                saveMeta(js, meta);
            }
            c = open(target, "/clip");
            c.setRequestMethod("POST");
            c.setDoOutput(true);
            c.setConnectTimeout(3000);
            c.setReadTimeout(60000);
            c.setFixedLengthStreamingMode(mp4.length());
            c.setRequestProperty("Content-Type", "video/mp4");
            c.setRequestProperty("X-QA-Name", mp4.getName());
            c.setRequestProperty("X-QA-Meta", URLEncoder.encode(meta.replace("\n", ""), "UTF-8"));
            try (InputStream in = new FileInputStream(mp4); OutputStream out = c.getOutputStream()) {
                byte[] b = new byte[64 * 1024];
                for (int n; (n = in.read(b)) > 0; ) out.write(b, 0, n);
            }
            if (c.getResponseCode() != 200) return false;
            JSONObject j = new JSONObject(read(c.getInputStream()));
            if (!j.optBoolean("ok") || j.optLong("bytes") != mp4.length()) return false;
            File sent = Clips.sent(ctx);
            mp4.renameTo(new File(sent, mp4.getName()));
            if (js.exists()) js.renameTo(new File(sent, js.getName()));
            Clips.prune(sent, 20);
            return true;
        } catch (Exception e) {
            Log.w(Recorder.TAG, "send " + mp4.getName() + ": " + e);
            return false;
        } finally {
            if (c != null) c.disconnect();
        }
    }

    private HttpURLConnection open(Target target, String path) throws Exception {
        HttpURLConnection c = (HttpURLConnection) new URL("http://" + target.address + path).openConnection();
        c.setUseCaches(false);
        c.setRequestProperty("X-QA-Mac", target.id);
        c.setRequestProperty("X-QA-Key", key());
        c.setRequestProperty("X-QA-Device", URLEncoder.encode(deviceName(), "UTF-8"));
        return c;
    }

    // ---- identity: a random key per install; the Mac approves it once ----

    private String key() {
        String k = sp.getString("key", null);
        if (k == null) {
            byte[] b = new byte[16];
            new SecureRandom().nextBytes(b);
            StringBuilder s = new StringBuilder();
            for (byte x : b) s.append(String.format("%02x", x));
            k = s.toString();
            sp.edit().putString("key", k).apply();
        }
        return k;
    }

    private String deviceName() {
        String n = Settings.Global.getString(ctx.getContentResolver(), Settings.Global.DEVICE_NAME);
        return n != null && !n.isEmpty() ? n : Build.MODEL;
    }

    // ---- Bonjour ----

    private void discover() {
        try {
            nsd = ctx.getSystemService(NsdManager.class);
            nsd.discoverServices(TYPE, NsdManager.PROTOCOL_DNS_SD, new NsdManager.DiscoveryListener() {
                @Override public void onServiceFound(NsdServiceInfo s) { resolve(s); }
                @Override public void onServiceLost(NsdServiceInfo s) { }
                @Override public void onDiscoveryStarted(String t) { }
                @Override public void onDiscoveryStopped(String t) { }
                @Override public void onStartDiscoveryFailed(String t, int e) { Log.w(Recorder.TAG, "bonjour failed " + e); }
                @Override public void onStopDiscoveryFailed(String t, int e) { }
            });
        } catch (Exception e) {
            Log.w(Recorder.TAG, "bonjour: " + e);
        }
    }

    @SuppressWarnings("deprecation")
    private void resolve(NsdServiceInfo s) {
        nsd.resolveService(s, new NsdManager.ResolveListener() {
            @Override public void onResolveFailed(NsdServiceInfo s, int e) { }
            @Override public void onServiceResolved(NsdServiceInfo r) {
                List<InetAddress> all = new ArrayList<>();
                if (Build.VERSION.SDK_INT >= 34) all.addAll(r.getHostAddresses());
                else if (r.getHost() != null) all.add(r.getHost());
                for (InetAddress a : all) {
                    if (a instanceof Inet4Address) {
                        found.add(a.getHostAddress() + ":" + r.getPort());
                        kick();
                        return;
                    }
                }
            }
        });
    }

    private static String read(InputStream in) throws Exception {
        ByteArrayOutputStream o = new ByteArrayOutputStream();
        byte[] b = new byte[8192];
        for (int n; (n = in.read(b)) > 0; ) o.write(b, 0, n);
        in.close();
        return o.toString("UTF-8");
    }
}

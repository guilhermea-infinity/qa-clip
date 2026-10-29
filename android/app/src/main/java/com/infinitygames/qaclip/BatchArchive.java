package com.infinitygames.qaclip;

import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.util.List;
import java.util.ArrayList;
import java.util.Locale;
import java.util.zip.ZipEntry;
import java.util.zip.ZipOutputStream;

/** Portable recording container; no Android dependency, so the desktop contract can be tested on a JVM. */
final class BatchArchive {
    static final int MAX_CLIPS = 100;
    static final long MAX_BYTES = 2L * 1024 * 1024 * 1024;

    static String clipName(int index) { return String.format(Locale.ROOT, "clips/%03d.mp4", index + 1); }

    static List<List<File>> parts(List<File> clips) throws IOException {
        List<List<File>> parts = new ArrayList<>();
        List<File> current = new ArrayList<>(); long bytes = 0;
        for (File clip : clips) {
            long size = clip.length();
            if (size > MAX_BYTES - 1024 * 1024) throw new IOException("One recording is larger than 2 GB");
            if (!current.isEmpty() && (current.size() == MAX_CLIPS || bytes + size > MAX_BYTES - 1024 * 1024)) {
                parts.add(current); current = new ArrayList<>(); bytes = 0;
            }
            current.add(clip); bytes += size;
        }
        if (!current.isEmpty()) parts.add(current);
        return parts;
    }

    static void write(File destination, List<File> clips, String manifest) throws IOException {
        if (clips.isEmpty() || clips.size() > MAX_CLIPS) throw new IOException("Share a batch with 1–100 recordings");
        long size = 0;
        for (File clip : clips) {
            if (!clip.isFile() || !clip.getName().endsWith(".mp4")) throw new IOException("A recording is unavailable");
            size += clip.length();
        }
        if (size > MAX_BYTES - 1024 * 1024) throw new IOException("This batch is larger than 2 GB");
        try (ZipOutputStream out = new ZipOutputStream(new FileOutputStream(destination))) {
            out.setLevel(0); // Videos are already compressed. Stream them without keeping them in memory.
            out.putNextEntry(new ZipEntry("manifest.json"));
            out.write(manifest.getBytes(StandardCharsets.UTF_8)); out.closeEntry();
            byte[] buffer = new byte[64 * 1024];
            for (int i = 0; i < clips.size(); i++) {
                out.putNextEntry(new ZipEntry(clipName(i)));
                try (FileInputStream in = new FileInputStream(clips.get(i))) {
                    for (int n; (n = in.read(buffer)) != -1;) out.write(buffer, 0, n);
                }
                out.closeEntry();
            }
        } catch (IOException error) {
            destination.delete(); throw error;
        }
    }
}

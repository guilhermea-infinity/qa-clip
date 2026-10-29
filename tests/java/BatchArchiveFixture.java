package com.infinitygames.qaclip;

import java.io.File;
import java.nio.file.Files;
import java.util.Arrays;

/** Exercise the exact ZIP writer shipped in the APK, using synthetic videos from the Python tests. */
public final class BatchArchiveFixture {
    public static void main(String[] args) throws Exception {
        String manifest = Files.readString(new File(args[1]).toPath());
        BatchArchive.write(new File(args[0]), Arrays.asList(new File(args[2]), new File(args[2])), manifest);
        java.util.List<File> large = new java.util.ArrayList<>();
        for (int i = 0; i < 3; i++) {
            File f = new File(new File(args[0]).getParentFile(), "sparse-" + i + ".mp4");
            try (java.io.RandomAccessFile out = new java.io.RandomAccessFile(f, "rw")) { out.setLength(750L * 1024 * 1024); }
            large.add(f);
        }
        if (BatchArchive.parts(large).size() != 2) throw new AssertionError("Large sessions must split into shareable parts");
        for (File f : large) f.delete();
    }
}

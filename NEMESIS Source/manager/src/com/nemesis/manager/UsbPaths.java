package com.nemesis.manager;

import java.io.File;
import java.io.IOException;

/** Confines Manager installation inputs to regular files on the mounted USB root. */
final class UsbPaths {
    private UsbPaths() {
    }

    static boolean contains(String root, String path) {
        if (root == null || path == null || root.length() == 0 || path.length() == 0) return false;
        File usb = new File(root);
        File file = new File(path);
        if (!usb.isAbsolute() || !file.isAbsolute()) return false;
        try {
            usb = usb.getCanonicalFile();
            file = file.getCanonicalFile();
            return usb.isDirectory() && file.isFile()
                    && file.getPath().startsWith(usb.getPath() + File.separator);
        } catch (IOException e) {
            return false;
        } catch (SecurityException e) {
            return false;
        }
    }
}

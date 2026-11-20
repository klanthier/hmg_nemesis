package com.nemesis.manager;

import java.io.File;

/** Exercises USB confinement using real files, sibling paths, and symlinks. */
public final class UsbPathsRun {
    private static int checks;

    private static void check(boolean ok, String what) {
        if (!ok) throw new AssertionError(what);
        checks++;
    }

    public static void main(String[] args) {
        String base = args[0];
        String root = base + "/usb";
        check(UsbPaths.contains(root, root + "/package.zip"), "root package");
        check(UsbPaths.contains(root, root + "/packages/dependency.zip"), "nested dependency");
        check(UsbPaths.contains(root, root + "/packages/../package.zip"), "safe normalization");
        check(UsbPaths.contains(root, root + "/inside-link.zip"), "link inside USB root");
        check(!UsbPaths.contains(root, base + "/cache/nemesis-update.zip"), "stale online update");
        check(!UsbPaths.contains(root, root + "/../cache/nemesis-update.zip"), "traversal escape");
        check(!UsbPaths.contains(root, root + "-sibling/package.zip"), "prefix sibling");
        check(!UsbPaths.contains(root, root + "/outside-link.zip"), "symlink escape");
        check(!UsbPaths.contains(root, root + "/missing.zip"), "missing file");
        check(!UsbPaths.contains(root, root + "/packages"), "directory input");
        check(!UsbPaths.contains(root, "package.zip"), "relative input");
        check(!UsbPaths.contains("usb", root + "/package.zip"), "relative root");
        check(!UsbPaths.contains(root, "https://example.invalid/package.zip"), "URL input");
        check(!UsbPaths.contains(null, root + "/package.zip"), "missing root");
        check(!UsbPaths.contains(root, null), "missing input");
        check(!UsbPaths.contains("", root + "/package.zip"), "empty root");
        check(!UsbPaths.contains(root, ""), "empty input");
        check(new File(root + "/package.zip").delete(), "simulate removal");
        check(!UsbPaths.contains(root, root + "/package.zip"), "removed file");
        System.out.println("USB path confinement: " + checks + " checks passed");
    }
}

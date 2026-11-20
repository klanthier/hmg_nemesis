package com.nemesis.manager;

import android.content.Context;

import org.json.JSONObject;

import java.io.File;
import java.io.IOException;
import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.atomic.AtomicBoolean;

/** Offline replacement for the portal; keeps existing USB callers unchanged. */
final class Portal {
    static final class Update {
        String version;
        String url;
        String sha256;
    }

    private Portal() {
    }

    static Update latestUpdate(Context c, String current, String os, String model) throws Exception {
        return null;
    }

    static List<StoreList.Entry> catalog(Context c) throws Exception {
        return new ArrayList<StoreList.Entry>();
    }

    static JSONObject descriptor(Context c, String id) throws Exception {
        throw offline();
    }

    static boolean useTelematics(Context c) {
        return false;
    }

    static void setUseTelematics(Context c, boolean on) {
        // Online services cannot be enabled in this build.
    }

    static File download(Context c, String url, String sha256, String name) throws Exception {
        throw offline();
    }

    static final class Cancelled extends IOException {
    }

    static File download(Context c, String url, String sha256, String name, AtomicBoolean cancel) throws Exception {
        throw offline();
    }

    private static IOException offline() {
        return new IOException("Online services are disabled in this USB-only build.");
    }
}

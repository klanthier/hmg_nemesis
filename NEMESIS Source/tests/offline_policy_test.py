#!/usr/bin/env python3
"""Exercise the offline compatibility API and broadcast routing on the host."""
import re
import subprocess
import tempfile
from pathlib import Path

from check_manager_apk import NETWORK_CODE

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "manager/src/com/nemesis/manager"
STUBS = {
    "android/content/Context.java": """package android.content;
public class Context {
    public Intent started;
    public Object startService(Intent i) { started = i; return null; }
}""",
    "android/content/Intent.java": """package android.content;
public class Intent {
    private String action;
    public Intent(Context c, Class<?> cls) {}
    public String getAction() { return action; }
    public Intent setAction(String s) { action = s; return this; }
}""",
    "android/content/BroadcastReceiver.java": """package android.content;
public abstract class BroadcastReceiver { public abstract void onReceive(Context c, Intent i); }""",
    "android/os/SystemClock.java": """package android.os;
public class SystemClock { public static long elapsedRealtime() { return 1; } }""",
    "org/json/JSONObject.java": "package org.json; public class JSONObject {}",
    "com/nemesis/manager/UpdateService.java": """package com.nemesis.manager;
class UpdateService {
    static final String ACTION_ANDROID_UP = "com.nemesis.manager.ANDROID_UP";
    static final String ACTION_TICK = "com.nemesis.manager.UPDATE_TICK";
    static final String ACTION_WOKE = "com.nemesis.manager.SCREEN_BACK";
}""",
    "com/nemesis/manager/AutoLaunch.java": """package com.nemesis.manager;
class AutoLaunch {
    static final String ACTION_SCREEN_OFF = "off", ACTION_SCREEN_ON = "on";
    static boolean off;
    static void markOff(android.content.Context c) { off = true; }
    static boolean takeOff(android.content.Context c, long t) { boolean v = off; off = false; return v; }
}""",
    "com/nemesis/manager/OfflinePolicyRun.java": """package com.nemesis.manager;
import android.content.Context;
import android.content.Intent;
import java.io.IOException;
import java.util.concurrent.atomic.AtomicBoolean;
public class OfflinePolicyRun {
    static void check(boolean ok) { if (!ok) throw new AssertionError(); }
    public static void main(String[] args) throws Exception {
        check(Portal.latestUpdate(null, "1", "private-os", "private-model") == null);
        check(Portal.catalog(null).isEmpty());
        for (boolean on : new boolean[] {true, false}) {
            Portal.setUseTelematics(null, on);
            check(!Portal.useTelematics(null));
        }
        int blocked = 0;
        try { Portal.descriptor(null, "test"); } catch (IOException expected) { blocked++; }
        try { Portal.download(null, "unused", "", "unused"); } catch (IOException expected) { blocked++; }
        try { Portal.download(null, "unused", "", "unused", new AtomicBoolean(false)); }
        catch (IOException expected) { blocked++; }
        check(blocked == 3);
        Context c = new Context();
        EventReceiver receiver = new EventReceiver();
        Intent intent = new Intent(c, UpdateService.class);
        receiver.onReceive(c, intent.setAction(UpdateService.ACTION_TICK));
        check(c.started == null);
        receiver.onReceive(c, intent.setAction(UpdateService.ACTION_ANDROID_UP));
        check(UpdateService.ACTION_ANDROID_UP.equals(c.started.getAction()));
        c.started = null;
        receiver.onReceive(c, intent.setAction(AutoLaunch.ACTION_SCREEN_OFF));
        check(c.started == null);
        receiver.onReceive(c, intent.setAction(AutoLaunch.ACTION_SCREEN_ON));
        check(UpdateService.ACTION_WOKE.equals(c.started.getAction()));
        c.started = null;
        receiver.onReceive(c, intent.setAction("unknown"));
        receiver.onReceive(c, null);
        check(c.started == null);
        System.out.println("OK: offline Portal API, ignored update tick, boot/wake routing preserved");
    }
}""",
}


def main() -> None:
    for source in SRC.glob("*.java"):
        assert not NETWORK_CODE.search(source.read_bytes()), "network API or endpoint: " + str(source)
    # Keep automatic update work disconnected even if its old helper methods remain.
    service = (SRC / "UpdateService.java").read_text().split("protected void onHandleIntent", 1)[1]
    service = service.split("/**", 1)[0]
    assert not re.search(r"\b(?:backgroundCheck|packageCheck|fetch|latest)\s*\(", service)
    with tempfile.TemporaryDirectory(prefix="nemesis-offline-") as temporary:
        out = Path(temporary)
        sources = [SRC / name for name in ("Portal.java", "StoreList.java", "UpdateRule.java", "EventReceiver.java")]
        for name, text in STUBS.items():
            path = out / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text)
            sources.append(path)
        subprocess.check_call(["javac", "-source", "1.7", "-target", "1.7", "-d", str(out)]
                              + [str(source) for source in sources])
        subprocess.check_call(["java", "-cp", str(out), "com.nemesis.manager.OfflinePolicyRun"])


if __name__ == "__main__":
    main()

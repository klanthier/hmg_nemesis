#!/usr/bin/env python3
"""Validate the newly compiled Installer APK without executing Android code."""
import subprocess
import zipfile
from pathlib import Path
from check_manager_apk import check_offline_apk

ROOT = Path(__file__).resolve().parents[2] / 'USB package path/installer'
apk = ROOT / 'NEMESIS-Installer.apk'
check_offline_apk(apk)
with zipfile.ZipFile(apk) as z:
    names = z.namelist()
    assert len(names) == len(set(names)), 'duplicate APK entries'
    assert z.testzip() is None, 'bad ZIP CRC'
    dex = z.read('classes.dex')
    assert dex.startswith(b'dex\n035\x00'), 'expected KitKat DEX 035'
    assert [n for n in names if n.endswith('.dex')] == ['classes.dex']
    assert not any(n.startswith('lib/') for n in names), 'unexpected native library'
    for src in (ROOT / 'src/com/nemesis/installer').glob('*.java'):
        assert ('Lcom/nemesis/installer/' + src.stem + ';').encode() in dex, src
info = subprocess.check_output(['aapt', 'dump', 'badging', str(apk)], text=True)
assert "package: name='com.nemesis.installer'" in info
assert "sdkVersion:'19'" in info
assert "android.permission.INTERNET" not in info
print('OK: freshly compiled Installer APK structure, source classes, API 19 and no Internet permission')

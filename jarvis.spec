# PyInstaller spec - build with:  pyinstaller --noconfirm jarvis.spec
from PyInstaller.utils.hooks import collect_all

datas, binaries, hiddenimports = [(".env.example", ".")], [], []
for pkg in ("speech_recognition", "sounddevice", "edge_tts", "vosk", "pystray", "PIL", "psutil"):
    try:
        d, b, h = collect_all(pkg)
        datas += d; binaries += b; hiddenimports += h
    except Exception as e:
        print("skip optional package:", pkg, e)

# Optional offline speech model: put the unzipped "model" folder next to this file and it gets bundled.
import os
if os.path.isdir("model"):
    datas.append(("model", "model"))

a = Analysis(
    ["jarvis.py"],
    pathex=["."],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports + ["jarvis.app", "jarvis.skills", "jarvis.ui", "jarvis.tray", "jarvis.winctl",
                                   "jarvis.extras", "jarvis.urdu", "jarvis.newsdesk",
                                   "jarvis.features", "jarvis.briefing", "jarvis.docs", "jarvis.agents", "jarvis.modes",
                                   "jarvis.extras2", "jarvis.panel"],
    excludes=["pytest", "unittest"],
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="Jarvis",
    console=False,                      # no black console window
    icon="installer/jarvis.ico",
)
coll = COLLECT(exe, a.binaries, a.datas, name="Jarvis")   # -> dist\Jarvis\Jarvis.exe

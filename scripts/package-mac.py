#!/usr/bin/env python3
"""Build a movable native macOS app with embedded Python; no source checkout needed at runtime."""
import argparse
import os
import platform
import plistlib
import importlib.metadata
import shutil
import subprocess
import sys
from urllib.request import urlopen
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERSION = '0.7.0'


def run(*args):
    subprocess.run([str(a) for a in args], check=True, cwd=ROOT)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'out/mac')
    parser.add_argument('--work', type=Path, default=ROOT / 'work/mac-package')
    a = parser.parse_args()
    if platform.system() != 'Darwin': parser.error('Build on macOS with Xcode command-line tools installed')
    output, work = a.output.expanduser().resolve(), a.work.expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True); work.mkdir(parents=True, exist_ok=True)
    bundle = output / 'Playtest Demon.app'
    if bundle.exists(): shutil.rmtree(bundle)
    resources = bundle / 'Contents/Resources'; resources.mkdir(parents=True)
    macos = bundle / 'Contents/MacOS'; macos.mkdir()
    command = [sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean', '--onedir', '--name', 'PlaytestDemonService',
               '--distpath', str(work / 'dist'), '--workpath', str(work / 'build'), '--specpath', str(work), '--paths', str(ROOT/'mac'),
               '--add-data', f'{ROOT}/mac/qa-desk.py:.', '--add-data', f'{ROOT}/mac/qa-inbox.py:.',
               '--add-data', f'{ROOT}/mac/desk-ui:desk-ui', '--add-data', f'{ROOT}/mac/prompts:prompts']
    run(*command, ROOT/'mac/service.py')
    shutil.copytree(work/'dist/PlaytestDemonService', resources/'service', symlinks=True)
    run('swiftc', '-swift-version', '5', '-parse-as-library', '-O', '-target', platform.machine()+'-apple-macos14.0', '-framework', 'AppKit', '-framework', 'WebKit', ROOT/'mac/native/PlaytestDemon.swift', '-o', macos/'PlaytestDemon')
    run('swift', ROOT/'mac/native/make-icon.swift', work/'icon.png')
    iconset = work/'Demon.iconset'; iconset.mkdir(exist_ok=True)
    for size in (16,32,128,256,512):
        for scale in (1,2):
            name = f'icon_{size}x{size}' + ('@2x' if scale == 2 else '') + '.png'
            run('sips', '-z', str(size*scale), str(size*scale), work/'icon.png', '--out', iconset/name)
    run('iconutil', '-c', 'icns', iconset, '-o', resources/'Demon.icns')
    info = {'CFBundleIdentifier':'com.infinitygames.playtestdemon', 'CFBundleName':'Playtest Demon', 'CFBundleDisplayName':'Playtest Demon',
            'CFBundleExecutable':'PlaytestDemon', 'CFBundlePackageType':'APPL', 'CFBundleShortVersionString':VERSION, 'CFBundleVersion':'1',
            'CFBundleIconFile':'Demon.icns', 'LSMinimumSystemVersion':'14.0', 'NSHighResolutionCapable':True,
            'NSAppTransportSecurity':{'NSAllowsLocalNetworking':True},
            'NSLocalNetworkUsageDescription':'Receive playtest recordings from your Android phone over Wi-Fi.',
            'NSDesktopFolderUsageDescription':'Keep your playtest recordings and approved requests in QA-Inbox on your Desktop.'}
    (bundle/'Contents/Info.plist').write_bytes(plistlib.dumps(info))
    shutil.copy2(ROOT/'LICENSE', resources/'LICENSE.txt')
    (resources/'README.txt').write_text('Playtest Demon '+VERSION+'\nDouble-click the app. Closing its window keeps receiving; Cmd+Q stops the desk.\nYour data stays in ~/Desktop/QA-Inbox. Logs: ~/Library/Logs/Playtest Demon.\nThe app includes Python, Pillow and jsonschema. ffmpeg, whisper/model, the selected AI CLI and GitHub CLI are installed separately; see the project setup guide.\nBuilt for '+platform.machine()+'. Locally ad-hoc signed; not Apple-notarized.\n')
    notices = resources/'Third-party notices'; notices.mkdir()
    for name in ('Pillow', 'jsonschema', 'jsonschema-specifications', 'referencing', 'rpds-py', 'attrs', 'pyinstaller'):
        try:
            dist = importlib.metadata.distribution(name)
            for file in dist.files or []:
                if any(word in file.name.lower() for word in ('license', 'copying', 'notice')) and file.suffix.lower() in ('', '.txt', '.rst', '.md'):
                    src = dist.locate_file(file)
                    if src.is_file(): shutil.copy2(src, notices/(name+'-'+file.name))
        except importlib.metadata.PackageNotFoundError: pass
    (notices/'Python.txt').write_text('Python runtime: '+sys.version+'\nPython Software Foundation License: https://docs.python.org/3/license.html\n')
    python_license = 'https://raw.githubusercontent.com/python/cpython/v'+platform.python_version()+'/LICENSE'
    with urlopen(python_license, timeout=30) as response:
        (notices/'Python-LICENSE.txt').write_bytes(response.read())
    for candidate in (Path(sys.base_prefix)/'LICENSE.txt', Path(sys.base_prefix)/'Resources/English.lproj/License.rtf'):
        if candidate.is_file(): shutil.copy2(candidate, notices/('Python-'+candidate.name))
    run('codesign', '--force', '--deep', '--sign', '-', bundle)
    run('codesign', '--verify', '--deep', '--strict', bundle)
    archive = output / f'Playtest-Demon-{VERSION}-macOS-{platform.machine()}.zip'
    if archive.exists(): archive.unlink()
    run('ditto', '-c', '-k', '--sequesterRsrc', '--keepParent', bundle, archive)
    staging = work/'installer'
    if staging.exists(): shutil.rmtree(staging)
    staging.mkdir()
    run('ditto', bundle, staging/bundle.name)
    (staging/'Applications').symlink_to('/Applications', target_is_directory=True)
    (staging/'Start here.txt').write_text('Drag Playtest Demon into Applications, then double-click it.\nClose the window to keep receiving clips; Cmd+Q quits.\nExisting data stays in ~/Desktop/QA-Inbox.\nApple Silicon build. First-time Mac dependencies/CLI login still need setup.\nProject setup: https://github.com/webavenue/playtest-demon#install-with-your-agent\nLocally signed, not Apple-notarized. On another Mac, macOS may require Privacy & Security > Open Anyway.\n')
    disk = output/f'Playtest-Demon-{VERSION}-macOS-{platform.machine()}.dmg'
    if disk.exists(): disk.unlink()
    run('hdiutil', 'create', '-volname', 'Playtest Demon', '-srcfolder', staging, '-ov', '-format', 'UDZO', disk)
    print(f'App: {bundle}\nZIP: {archive}\nInstaller: {disk}')


if __name__ == '__main__': main()

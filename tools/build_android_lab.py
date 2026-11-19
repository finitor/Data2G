#!/usr/bin/env python3
"""Build the standalone Lab APK with the installed SDK/NDK/JDK; no Qt or Gradle.

Uses the installed toolchain; never dispatches CI. Device installation occurs
only with --install SERIAL.
The debug APK is for local diagnostics, not a release artifact.
"""
import argparse
import hashlib
import json
import os
import re
from pathlib import Path
import shutil
import subprocess
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def run(args, env):
    subprocess.run([str(x) for x in args], cwd=ROOT, env=env, check=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--sdk', type=Path, default=Path(os.environ.get('ANDROID_HOME', Path.home() / 'Library/Android/sdk')))
    ap.add_argument('--ndk', type=Path)
    ap.add_argument('--java-home', type=Path, default=Path(os.environ['JAVA_HOME']) if 'JAVA_HOME' in os.environ else None)
    ap.add_argument('--abi', choices=['arm64-v8a', 'x86_64'], default='arm64-v8a')
    ap.add_argument('--jobs', type=int, default=6)
    ap.add_argument('--install', metavar='SERIAL', help='install on this explicit ADB device only')
    args = ap.parse_args()
    env = os.environ.copy()
    if args.java_home:
        env['JAVA_HOME'] = str(args.java_home)
        env['PATH'] = str(args.java_home / 'bin') + os.pathsep + env.get('PATH', '')
    sdk = args.sdk.resolve()
    version = lambda p: tuple(int(x) for x in p.name.split('.') if x.isdigit())
    ndk = args.ndk or max((sdk / 'ndk').iterdir(), key=version)
    bt = max((sdk / 'build-tools').iterdir(), key=version)
    android = sdk / 'platforms/android-35/android.jar'
    if not android.is_file() or not shutil.which('javac', path=env['PATH']):
        ap.error('install SDK platform 35 and a JDK, or supply --sdk/--java-home')
    build = ROOT / f'native/build-android-lab-{args.abi}'
    classes, dex = build / 'classes', build / 'dex'
    classes.mkdir(parents=True, exist_ok=True)
    dex.mkdir(exist_ok=True)
    source = ROOT / 'native/android-lab'
    # Include new/untracked harness sources in the identity; HEAD alone would
    # wrongly identify a prototype as unchanged upstream.
    digest = hashlib.sha256()
    files = [ROOT / 'native/CMakeLists.txt', Path(__file__).resolve()]
    for folder in (ROOT / 'native/lab', ROOT / 'native/core', ROOT / 'native/apps', ROOT / 'native/tests', ROOT / 'native/cmake', ROOT / 'native/third_party/pocketfft', source):
        files.extend(p for p in folder.rglob('*') if p.is_file() and p.name != '.DS_Store' and '__pycache__' not in p.parts and p.suffix != '.pyc')
    for p in sorted(files):
        digest.update(str(p.relative_to(ROOT)).encode())
        digest.update(p.read_bytes())
    revision = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip() + '+' + digest.hexdigest()[:16]
    run(['cmake', '-S', source, '-B', build, '-G', 'Unix Makefiles',
         f'-DCMAKE_TOOLCHAIN_FILE={ndk}/build/cmake/android.toolchain.cmake',
         f'-DANDROID_ABI={args.abi}', '-DANDROID_PLATFORM=android-29', '-DCMAKE_BUILD_TYPE=RelWithDebInfo',
         f'-DDATA2G_LAB_REVISION={revision}'], env)
    run(['cmake', '--build', build, '--target', 'data2g_lab', 'lab_programs', '--parallel', args.jobs], env)
    java = sorted((source / 'src').rglob('*.java'))
    run(['javac', '--release', '8', '-classpath', android, '-d', classes, *java], env)
    run([bt / 'd8', '--min-api', '29', '--lib', android, '--output', dex, *sorted(classes.rglob('*.class'))], env)
    assets = build / 'assets'
    assets.mkdir(exist_ok=True)
    shutil.copytree(source / 'assets', assets, dirs_exist_ok=True)
    notices = assets / 'licenses'
    notices.mkdir(exist_ok=True)
    for name in ('LICENSE', 'LICENSE_exception', 'LICENSE_ion'):
        shutil.copyfile(ROOT / name, notices / name)
    pocketfft = (ROOT / 'native/third_party/pocketfft/pocketfft_hdronly.h').read_text()
    (notices / 'pocketfft.txt').write_text(pocketfft.split('*/', 1)[0] + '*/\n')
    ndk_notices = list((ndk / 'toolchains/llvm/prebuilt').glob('*/NOTICE'))
    if len(ndk_notices) == 1:
        shutil.copyfile(ndk_notices[0], notices / 'android-ndk-NOTICE.txt')
    programs = sorted((build / 'programs').glob('liblab_*.so'))
    available = {p.name[len('liblab_'):-3] for p in programs}
    suites = []
    for test in sorted((ROOT / 'native/tests').glob('test_*.cpp')):
        suites.append(dict(id=test.stem, available=test.stem in available,
                           source=str(test.relative_to(ROOT)),
                           reason='' if test.stem in available else 'Requires desktop Qt/station or external Hamlib backend'))
    suites.append(dict(id='test_gui', available=False, source='native/gui/test_gui.cpp', reason='Qt Widgets desktop UI'))
    (assets / 'native-suites.json').write_text(json.dumps(dict(schema=1, suites=suites), indent=2))
    core_version = re.search(r'project\(data2g_native VERSION ([0-9]+\.[0-9]+\.[0-9]+)', (ROOT / 'native/CMakeLists.txt').read_text())
    if not core_version:
        raise RuntimeError('cannot read native core version')
    base = build / 'base.apk'
    run([bt / 'aapt2', 'link', '-I', android, '--manifest', source / 'AndroidManifest.xml',
         '--version-code', '4', '--version-name', core_version.group(1) + '-lab4', '-A', assets, '-o', base], env)
    with zipfile.ZipFile(base, 'a') as archive:
        archive.write(dex / 'classes.dex', 'classes.dex')
        # Keep symbols beside the build for profiling; strip only APK copies.
        llvm_bins = list((ndk / 'toolchains/llvm/prebuilt').glob('*/bin/llvm-strip'))
        if len(llvm_bins) != 1:
            raise RuntimeError('cannot locate llvm-strip')
        staging = build / 'apk-programs'
        staging.mkdir(exist_ok=True)
        for binary in [build / 'libdata2g_lab.so', *programs]:
            packaged = staging / binary.name
            shutil.copyfile(binary, packaged)
            run([llvm_bins[0], '--strip-unneeded', packaged], env)
            archive.write(packaged, f'lib/{args.abi}/{binary.name}')
        # Android provides its system libraries; package the NDK C++ shared runtime.
        triples = {'arm64-v8a': 'aarch64-linux-android', 'x86_64': 'x86_64-linux-android'}
        runtimes = list((ndk / 'toolchains/llvm/prebuilt').glob(f'*/sysroot/usr/lib/{triples[args.abi]}/libc++_shared.so'))
        if len(runtimes) != 1:
            raise RuntimeError('cannot locate the NDK C++ shared runtime')
        archive.write(runtimes[0], f'lib/{args.abi}/libc++_shared.so')
    apk = build / 'data2g-lab.apk'
    run([bt / 'zipalign', '-P', '16', '-f', '4', base, apk], env)
    run([bt / 'apksigner', 'sign', '--ks', ROOT / 'native/android-app/ci-debug.keystore',
         '--ks-pass', 'pass:android', '--ks-key-alias', 'androiddebugkey', '--key-pass', 'pass:android', apk], env)
    run([bt / 'apksigner', 'verify', apk], env)
    print(f'Built: {apk}\nSource: {revision}', flush=True)
    if args.install:
        run([sdk / 'platform-tools/adb', '-s', args.install, 'install', '-r', apk], env)


if __name__ == '__main__':
    main()

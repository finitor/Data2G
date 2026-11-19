#!/usr/bin/env python3
"""Run HTML archive checks with Android's Java runtime, without installing an APK.

Uses the frozen, checked-in 26-suite phone report as a rendering fixture.
Writes only its own /data/local/tmp directory on the explicitly selected device.
No modem tests, training, downloads or hosted CI are run by this tool.
"""
import argparse
import json
import os
from pathlib import Path
import shlex
import subprocess
import tempfile
import uuid

ROOT = Path(__file__).resolve().parents[1]


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--serial', required=True)
    ap.add_argument('--sdk', type=Path, default=Path.home() / 'Library/Android/sdk')
    ap.add_argument('--java-home', type=Path, required=True)
    ap.add_argument('--output', type=Path, default=ROOT / 'native/build-loopback/html-export-check')
    args = ap.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env['JAVA_HOME'] = str(args.java_home)
    env['PATH'] = str(args.java_home / 'bin') + os.pathsep + env.get('PATH', '')
    version = lambda p: tuple(int(v) for v in p.name.split('.') if v.isdigit())
    build_tools = max((args.sdk / 'build-tools').iterdir(), key=version)
    android = args.sdk / 'platforms/android-35/android.jar'
    adb = args.sdk / 'platform-tools/adb'

    def run(command):
        subprocess.run([str(v) for v in command], cwd=ROOT, env=env, check=True)

    def remote(command):
        run([adb, '-s', args.serial, 'shell', shlex.join([str(v) for v in command])])

    package = Path('org/cleverdomain/data2g/lab')
    source = ROOT / 'native/android-loopback'
    with tempfile.TemporaryDirectory(prefix='data2g-html-check-', dir=args.output) as scratch:
        scratch = Path(scratch)
        classes, dex, fixture = [scratch / n for n in ['classes', 'dex', 'fixture']]
        for folder in [classes, dex, fixture]:
            folder.mkdir()
        report = json.loads((ROOT / 'docs/loopback-lab/redmi-10c-lab3-native-final-2026-11-18.json').read_text())
        profile = report.pop('profiling')
        (fixture / report['profiling_file']).write_text(json.dumps(profile))
        rows = []
        for i, result in enumerate(report['trials']):
            name = f'case-{i:06d}-attempt-{i + 1:06d}.json'
            (fixture / name).write_text(json.dumps(result))
            rows.append(dict(ordinal=i, file=name, workload_kind=result['workload_kind'], channel=result.get('channel', ''), outcome=result['outcome']))
        (fixture / 'index.jsonl').write_text(''.join(json.dumps(row) + '\n' for row in rows))
        (fixture / 'manifest.json').write_text(json.dumps(report))
        run([args.java_home / 'bin/javac', '--release', '8', '-classpath', android, '-d', classes,
             source / 'src' / package / 'RunStore.java', source / 'src' / package / 'HtmlReport.java',
             source / 'test' / package / 'HtmlReportCheck.java'])
        run([build_tools / 'd8', '--min-api', '29', '--lib', android, '--output', dex, *sorted(classes.rglob('*.class'))])
        task = '/data/local/tmp/data2g-html-check-' + uuid.uuid4().hex[:12]
        remote(['mkdir', '-p', task])
        run([adb, '-s', args.serial, 'push', dex / 'classes.dex', task + '/check.dex'])
        run([adb, '-s', args.serial, 'push', source / 'assets/report.html', task + '/template.html'])
        run([adb, '-s', args.serial, 'push', fixture, task + '/fixture'])
        remote(['CLASSPATH=' + task + '/check.dex', 'app_process', '/', 'org.cleverdomain.data2g.lab.HtmlReportCheck',
                task + '/fixture', task + '/template.html', task + '/real.zip', task + '/qa'])
        run([adb, '-s', args.serial, 'pull', task + '/real.zip', args.output / 'real.zip'])
        run([adb, '-s', args.serial, 'pull', task + '/qa/fixture.zip', args.output / 'fixture.zip'])
        print(f'PASS: Android exporter checks; browser fixtures saved in {args.output}')


if __name__ == '__main__':
    main()

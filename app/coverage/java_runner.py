"""Java coverage: detects Maven or Gradle within a project dir and runs
JaCoCo, the standard JVM coverage instrumentation tool for both build
systems, then parses its XML report into this app's common file-coverage
shape (statements = JaCoCo's LINE counter, branches = its BRANCH counter).

Neither build tool needs the repo to have JaCoCo pre-configured:
  - Maven: the jacoco-maven-plugin goals are invoked directly by coordinate
    (`org.jacoco:jacoco-maven-plugin:VERSION:prepare-agent`/`:report`), which
    Maven supports without the plugin being declared in pom.xml.
  - Gradle: an init script (passed via --init-script, never written into the
    repo) applies the `jacoco` plugin and an XML-reporting task to every
    project, the Gradle equivalent of Maven's ad-hoc plugin invocation.
"""

import os
import re
import shutil
import signal
import stat
import subprocess
import tempfile
import xml.etree.ElementTree as ET

from app import config
from app.coverage.coverage_math import overall_from, safe_pct
from app.coverage.errors import CoverageRunError

JACOCO_PLUGIN_VERSION = "0.8.12"

# JaCoCo 0.8.12's bytecode instrumenter can't read class files compiled by
# very new/preview JDKs (e.g. "Unsupported class file major version 70" on
# JDK 26) — but it happily *runs* on any JDK, it just can't instrument
# classes newer than it understands. Compiling+testing with an older, widely-
# supported LTS JDK sidesteps that entirely, so we pin one for the Maven/
# Gradle subprocess rather than trusting whatever the backend host's default
# `java` happens to resolve to (which, on a dev box with several JDKs
# installed, can silently drift after something else installs a newer one).
_PREFERRED_JDK_VERSIONS = ["21", "17", "11"]


def _resolve_java_home() -> str | None:
    override = config.settings.java_home_for_coverage
    if override and os.path.isdir(override):
        return override

    java_home_tool = "/usr/libexec/java_home"  # macOS
    if os.path.exists(java_home_tool):
        for version in _PREFERRED_JDK_VERSIONS:
            result = subprocess.run(
                [java_home_tool, "-v", version], capture_output=True, text=True, timeout=10
            )
            if result.returncode == 0 and result.stdout.strip():
                return result.stdout.strip()

    candidates = []
    for version in _PREFERRED_JDK_VERSIONS:
        candidates += [
            f"/opt/homebrew/opt/openjdk@{version}/libexec/openjdk.jdk/Contents/Home",
            f"/usr/lib/jvm/java-{version}-openjdk",
            f"/usr/lib/jvm/java-{version}-openjdk-amd64",
        ]
    for path in candidates:
        if os.path.isdir(path):
            return path

    return None  # fall back to whatever the ambient environment already resolves


_MVN_CANDIDATES = [
    "/opt/homebrew/bin/mvn",
    "/opt/homebrew/opt/maven/bin/mvn",
    "/usr/local/bin/mvn",
    "/usr/local/opt/maven/bin/mvn",
]
_GRADLE_CANDIDATES = [
    "/opt/homebrew/bin/gradle",
    "/opt/homebrew/opt/gradle/bin/gradle",
    "/usr/local/bin/gradle",
    "/usr/local/opt/gradle/bin/gradle",
]


def _resolve_on_path_or_candidates(executable: str, candidates: list[str]) -> str | None:
    """shutil.which() only sees the backend process's own PATH, which (e.g.
    inside an activated venv, or a service started with a minimal PATH) may
    not include Homebrew's bin dirs even though the tool is genuinely
    installed there -- check a handful of common install locations as a
    fallback, mirroring _resolve_java_home()'s approach below."""
    found = shutil.which(executable)
    if found:
        return found
    for path in candidates:
        if os.path.exists(path):
            return path
    return None


def _resolve_mvn() -> str | None:
    return _resolve_on_path_or_candidates("mvn", _MVN_CANDIDATES)


def _resolve_gradle() -> str | None:
    return _resolve_on_path_or_candidates("gradle", _GRADLE_CANDIDATES)


def _subprocess_env() -> dict | None:
    java_home = _resolve_java_home()
    if not java_home:
        return None
    env = os.environ.copy()
    env["JAVA_HOME"] = java_home
    env["PATH"] = os.path.join(java_home, "bin") + os.pathsep + env.get("PATH", "")
    return env

GRADLE_INIT_SCRIPT = """
allprojects {
    apply plugin: 'jacoco'
    jacoco {
        toolVersion = "%s"
    }
    tasks.withType(Test) {
        finalizedBy tasks.matching { it.name == "jacocoTestReport" }
    }
    tasks.matching { it.name == "jacocoTestReport" }.configureEach {
        reports {
            xml.required.set(true)
        }
    }
}
""" % JACOCO_PLUGIN_VERSION


def _run(cmd: list[str], cwd: str, timeout: int, label: str, env: dict | None = None) -> subprocess.CompletedProcess:
    """Runs a build command with a timeout, guaranteeing the WHOLE process
    tree it spawns is gone afterwards.

    Maven/Gradle fork their own test-runner JVM (Surefire/Gradle test
    workers), which for a Selenium-style suite then launches a real browser
    -- plain `subprocess.run(..., timeout=...)` only kills the direct
    mvn/gradle child on timeout, leaving that forked JVM (and any browser it
    opened) running indefinitely as an orphaned process. Starting the
    process in its own session (`start_new_session=True`) lets us kill the
    entire process group via `os.killpg` instead of just the one PID.
    """
    try:
        process = subprocess.Popen(
            cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env,
            start_new_session=True,
        )
    except FileNotFoundError as e:
        raise CoverageRunError(f"{label} failed: {cmd[0]} not found on the backend host.") from e

    try:
        stdout, stderr = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait()
        raise CoverageRunError(f"{label} timed out after {timeout}s.") from None

    return subprocess.CompletedProcess(cmd, process.returncode, stdout, stderr)


def _make_executable(path: str) -> None:
    mode = os.stat(path).st_mode
    os.chmod(path, mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def _detect_testng_suite_file(repo_dir: str) -> str | None:
    """Many TestNG projects don't hard-code which suite XML to run in the
    POM — they read it from a Maven property (conventions vary by project:
    `testSuiteFile`, `suiteXmlFile`, or the surefire-native
    `surefire.suiteXmlFiles`), left undefined by default. Without a value,
    surefire's <suiteXmlFile>${...}</suiteXmlFile> resolves to nothing and
    surefire aborts (e.g. "testSuiteXmlFiles0 has null value") before it
    ever gets to run a single test.

    If exactly one root-level XML file looks like a TestNG suite descriptor
    (a `<suite ...>` root element), supply it under all three common
    property-name conventions — whichever one the POM actually references
    will pick it up, and the others are harmlessly unused.
    """
    try:
        entries = os.listdir(repo_dir)
    except OSError:
        return None

    candidates = []
    for name in entries:
        if not name.lower().endswith(".xml"):
            continue
        path = os.path.join(repo_dir, name)
        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                head = f.read(1000)
        except OSError:
            continue
        if re.search(r"<suite\b", head):
            candidates.append(name)

    return candidates[0] if len(candidates) == 1 else None


def _parse_jacoco_xml(report_path: str) -> dict:
    """JaCoCo's XML report carries a DOCTYPE pointing at an external DTD;
    strip it before parsing so ElementTree never attempts to fetch it."""
    with open(report_path, "r", encoding="utf-8", errors="replace") as f:
        content = f.read()
    content = re.sub(r"<!DOCTYPE[^>]*>", "", content, count=1)

    root = ET.fromstring(content)

    files = []
    for package in root.findall("package"):
        package_name = package.get("name", "")
        for sourcefile in package.findall("sourcefile"):
            counters = {c.get("type"): c for c in sourcefile.findall("counter")}
            line_counter = counters.get("LINE")
            branch_counter = counters.get("BRANCH")

            line_missed = int(line_counter.get("missed", 0)) if line_counter is not None else 0
            line_covered = int(line_counter.get("covered", 0)) if line_counter is not None else 0
            branch_missed = int(branch_counter.get("missed", 0)) if branch_counter is not None else 0
            branch_covered = int(branch_counter.get("covered", 0)) if branch_counter is not None else 0

            statements = line_missed + line_covered
            branches = branch_missed + branch_covered
            stmt_pct = safe_pct(line_covered, statements)
            branch_pct = safe_pct(branch_covered, branches)

            file_name = f"{package_name}/{sourcefile.get('name')}" if package_name else sourcefile.get("name")
            files.append(
                {
                    "file_name": file_name,
                    "statements": statements,
                    "statement_coverage": stmt_pct,
                    "branches": branches,
                    "branch_coverage": branch_pct,
                    "overall_coverage": overall_from(stmt_pct, branch_pct),
                }
            )

    totals = {c.get("type"): c for c in root.findall("counter")}
    total_line = totals.get("LINE")
    total_branch = totals.get("BRANCH")
    total_line_missed = int(total_line.get("missed", 0)) if total_line is not None else 0
    total_line_covered = int(total_line.get("covered", 0)) if total_line is not None else 0
    total_branch_missed = int(total_branch.get("missed", 0)) if total_branch is not None else 0
    total_branch_covered = int(total_branch.get("covered", 0)) if total_branch is not None else 0

    statement_coverage = safe_pct(total_line_covered, total_line_missed + total_line_covered)
    branch_coverage = safe_pct(total_branch_covered, total_branch_missed + total_branch_covered)

    return {
        "statement_coverage": statement_coverage,
        "branch_coverage": branch_coverage,
        "overall_coverage": overall_from(statement_coverage, branch_coverage),
        "files": sorted(files, key=lambda f: f["file_name"]),
    }


def _run_maven(repo_dir: str, log_fn, timeout: int) -> dict:
    mvnw = os.path.join(repo_dir, "mvnw")
    resolved_mvn = None
    if os.path.exists(mvnw):
        _make_executable(mvnw)
        mvn_cmd = ["./mvnw"]
        log_fn("info", "Using the repository's Maven wrapper (mvnw)...")
    else:
        resolved_mvn = _resolve_mvn()
        if resolved_mvn:
            mvn_cmd = [resolved_mvn]
            log_fn("info", f"Using the backend host's Maven installation ({resolved_mvn})...")
        else:
            raise CoverageRunError(
                "No Maven found: the repository has no mvnw wrapper and no `mvn` executable is "
                "installed on the backend host."
            )

    env = _subprocess_env()
    if resolved_mvn:
        # _resolve_mvn() may have found Maven outside the process's own PATH
        # (e.g. Homebrew's bin dir) -- put its directory on PATH for the
        # subprocess too, in case Maven itself shells out expecting it there.
        env = env or os.environ.copy()
        mvn_dir = os.path.dirname(resolved_mvn)
        env["PATH"] = mvn_dir + os.pathsep + env.get("PATH", "")
    if env:
        log_fn("info", f"Using JDK at {env.get('JAVA_HOME', 'the ambient JAVA_HOME')} for the build...")

    suite_props = []
    suite_file = _detect_testng_suite_file(repo_dir)
    if suite_file:
        log_fn("info", f"Detected TestNG suite file '{suite_file}' — passing it to Surefire.")
        suite_props = [f"-D{prop}={suite_file}" for prop in ("testSuiteFile", "surefire.suiteXmlFiles", "suiteXmlFile")]

    log_fn("info", "Running Maven tests with JaCoCo instrumentation (this compiles + runs the test suite)...")
    result = _run(
        mvn_cmd
        + [
            "-B",
            "-q",
            "-Dmaven.test.failure.ignore=true",
        ]
        + suite_props
        + [
            f"org.jacoco:jacoco-maven-plugin:{JACOCO_PLUGIN_VERSION}:prepare-agent",
            "test",
            f"org.jacoco:jacoco-maven-plugin:{JACOCO_PLUGIN_VERSION}:report",
        ],
        cwd=repo_dir,
        timeout=timeout,
        label="running Maven with JaCoCo",
        env=env,
    )

    report_path = os.path.join(repo_dir, "target", "site", "jacoco", "jacoco.xml")
    if not os.path.exists(report_path):
        tail = (result.stdout + "\n" + result.stderr).strip()[-1500:]
        raise CoverageRunError(f"Maven/JaCoCo did not produce a coverage report. Output tail:\n{tail}")

    log_fn("success", "Maven tests completed — parsing JaCoCo report...")
    return _parse_jacoco_xml(report_path)


def _run_gradle(repo_dir: str, log_fn, timeout: int) -> dict:
    gradlew = os.path.join(repo_dir, "gradlew")
    resolved_gradle = None
    if os.path.exists(gradlew):
        _make_executable(gradlew)
        gradle_cmd = ["./gradlew"]
        log_fn("info", "Using the repository's Gradle wrapper (gradlew)...")
    else:
        resolved_gradle = _resolve_gradle()
        if resolved_gradle:
            gradle_cmd = [resolved_gradle]
            log_fn("info", f"Using the backend host's Gradle installation ({resolved_gradle})...")
        else:
            raise CoverageRunError(
                "No Gradle found: the repository has no gradlew wrapper and no `gradle` executable is "
                "installed on the backend host."
            )

    env = _subprocess_env()
    if resolved_gradle:
        env = env or os.environ.copy()
        gradle_dir = os.path.dirname(resolved_gradle)
        env["PATH"] = gradle_dir + os.pathsep + env.get("PATH", "")
    if env:
        log_fn("info", f"Using JDK at {env.get('JAVA_HOME', 'the ambient JAVA_HOME')} for the build...")

    with tempfile.NamedTemporaryFile(mode="w", suffix=".gradle", delete=False) as init_file:
        init_file.write(GRADLE_INIT_SCRIPT)
        init_script_path = init_file.name

    try:
        log_fn("info", "Running Gradle tests with JaCoCo instrumentation (this compiles + runs the test suite)...")
        result = _run(
            gradle_cmd
            + [
                "--init-script",
                init_script_path,
                "test",
                "jacocoTestReport",
                "--continue",
                "-q",
            ],
            cwd=repo_dir,
            timeout=timeout,
            label="running Gradle with JaCoCo",
            env=env,
        )
    finally:
        os.unlink(init_script_path)

    candidate_paths = [
        os.path.join(repo_dir, "build", "reports", "jacoco", "test", "jacocoTestReport.xml"),
        os.path.join(repo_dir, "build", "reports", "jacoco", "jacocoTestReport.xml"),
    ]
    report_path = next((p for p in candidate_paths if os.path.exists(p)), None)
    if report_path is None:
        tail = (result.stdout + "\n" + result.stderr).strip()[-1500:]
        raise CoverageRunError(f"Gradle/JaCoCo did not produce a coverage report. Output tail:\n{tail}")

    log_fn("success", "Gradle tests completed — parsing JaCoCo report...")
    return _parse_jacoco_xml(report_path)


def run(repo_dir: str, log_fn=lambda level, message: None) -> dict:
    timeout = config.settings.coverage_job_timeout_seconds

    if os.path.exists(os.path.join(repo_dir, "pom.xml")):
        log_fn("info", "Detected Maven (pom.xml).")
        return _run_maven(repo_dir, log_fn, timeout)

    if any(
        os.path.exists(os.path.join(repo_dir, marker))
        for marker in ("build.gradle", "build.gradle.kts", "settings.gradle", "settings.gradle.kts")
    ):
        log_fn("info", "Detected Gradle (build.gradle/settings.gradle).")
        return _run_gradle(repo_dir, log_fn, timeout)

    raise CoverageRunError(
        "Detected a Java-looking project directory but found neither pom.xml (Maven) nor "
        "build.gradle/.kts (Gradle)."
    )

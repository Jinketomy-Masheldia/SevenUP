"""Exact reference gates. No approximate or silently substituted kernel."""

from .console import say

import shutil
import tempfile
from pathlib import Path

from .core import Project, digest_file, load_json, publish_directory, require, save_json
from .firmware import resource
from .img4 import split_image


def prepare_bootstrap_donor(project: Project) -> dict:
    """Apply SSHRD changes once and require the exact historical 15.6 donor."""
    source = resource(project, "iphone7_bootstrap", "KernelCache")
    lock = load_json(project.root / "profiles/kernel-reference.json")
    expected = lock["research_input_raw_sha256"]["iphone7_bootstrap"]
    destination = project.work / "kernel-inputs/iphone7_bootstrap"
    if destination.exists():
        record = load_json(destination / "receipt.json")
        require(record["source_sha256"] == digest_file(source, ("sha256",))["sha256"], "Bootstrap donor source changed.")
        for name, hashes in record["files"].items():
            require(Path(name).name == name, "Unexpected donor artifact path.")
            require(digest_file(destination / name, ("sha256",)) == hashes, f"Bootstrap donor artifact changed: {name}")
        require(record["patched_sha256"] == expected, "Cached patched donor is not the historical 15.6 donor.")
        return record
    destination.parent.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix=".donor-", dir=destination.parent))
    try:
        raw, patched, patch = work / "kernel.source.raw", work / "kernel.sshrd.raw", work / "kernel.bpatch"
        project.run([project.tool("img4"), "-i", source, "-o", raw])
        require(digest_file(raw, ("sha256",))["sha256"] == lock["input_recipes"]["iphone7_bootstrap"]["pristine_raw_sha256"],
                "The pristine 15.6 kernel does not match the pinned input.")
        project.run([project.tool("KPlooshFinder"), raw, patched])
        actual = digest_file(patched, ("sha256",))["sha256"]
        require(actual == expected, "The 15.6 SSHRD-patched donor differs from the historical donor. Stop before transplanting drivers.")
        project.run([project.tool("kerneldiff"), raw, patched, patch])
        record = {"kind": "sshrd-patched-donor", "version": "15.6", "build": "19G71",
                  "source_sha256": digest_file(source, ("sha256",))["sha256"],
                  "pristine_raw_sha256": digest_file(raw, ("sha256",))["sha256"],
                  "patched_sha256": actual, "historical_donor_match": True,
                  "patcher_sha256": digest_file(Path(project.tool("KPlooshFinder")), ("sha256",))["sha256"],
                  "files": {path.name: digest_file(path, ("sha256",)) for path in [raw, patched, patch]}}
        save_json(work / "receipt.json", record)
        publish_directory(work, destination)
        project.record("bootstrap-donor", {"folder": str(destination), "patched_sha256": actual,
                                           "historical_donor_match": True})
        say("15.6 SSHRD-patched donor rebuilt; byte-identical to the historical research input.", 'success')
        return record
    except BaseException:
        shutil.rmtree(work, ignore_errors=True)
        raise


def prepare_research_input(project: Project, role: str) -> dict:
    """Normalize each source exactly as it was used in the research pipeline."""
    if role == "iphone7_bootstrap":
        return prepare_bootstrap_donor(project)
    require(role in {"ipad_target", "iphone8_donor"}, "Unsupported kernel input role.")
    lock = load_json(project.root / "profiles/kernel-reference.json")
    recipe = lock["input_recipes"][role]
    source = resource(project, role, "KernelCache")
    destination = project.work / "kernel-inputs" / role
    if destination.exists():
        record = load_json(destination / "receipt.json")
        require(record["source_sha256"] == digest_file(source, ("sha256",))["sha256"], "Kernel input source changed.")
        actual = digest_file(destination / "kernel.research.raw", ("sha256",))["sha256"]
        require(actual == lock["research_input_raw_sha256"][role], "Cached research kernel input changed.")
        return record
    destination.parent.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix=".input-", dir=destination.parent))
    try:
        raw, result = work / "kernel.source.raw", work / "kernel.research.raw"
        project.run([project.tool("img4"), "-i", source, "-o", raw])
        require(digest_file(raw, ("sha256",))["sha256"] == recipe["pristine_raw_sha256"], "Pristine kernel input hash mismatch.")
        if recipe["mode"] == "KPlooshFinder":
            project.run([project.tool("KPlooshFinder"), raw, result])
        else:
            require(recipe["mode"] == "pristine", "Unknown kernel input transform.")
            shutil.copyfile(raw, result)
        actual = digest_file(result, ("sha256",))["sha256"]
        require(actual == lock["research_input_raw_sha256"][role], "Normalized kernel does not match the historical research input.")
        record = {"role": role, "mode": recipe["mode"], "source_sha256": digest_file(source, ("sha256",))["sha256"],
                  "raw_sha256": actual, "historical_input_match": True}
        save_json(work / "receipt.json", record)
        publish_directory(work, destination)
        project.record("kernel-input-" + role, record)
        say(f"Kernel input verified: {role}, transform={recipe['mode']}, historical input is byte-identical.", 'success')
        return record
    except BaseException:
        shutil.rmtree(work, ignore_errors=True)
        raise


def import_reference(project: Project, source: Path):
    """Development bridge while the research builders are being made standalone.

    This accepts only the frozen local artifact, never an arbitrary patched kernel.
    It is not represented as a clean-IPSW rebuild and is not redistributable input.
    """
    lock = load_json(project.root / "profiles/kernel-reference.json")
    require(source.is_file(), f"Kernel reference does not exist: {source}")
    hashes = digest_file(source)
    require(hashes["md5"] == lock["image_md5"] and hashes["sha256"] == lock["image_sha256"],
            "Kernel reference does not match the frozen HC3 artifact. No kernel was staged.")
    project.initialize()
    folder = project.work / "kernel"
    folder.mkdir(parents=True, exist_ok=True)
    destination = folder / "reference.img4"
    if destination.exists():
        require(destination.read_bytes() == source.read_bytes(), "An existing kernel reference differs.")
    else:
        shutil.copyfile(source, destination)
    raw = folder / "reference.raw"
    project.run([project.tool("img4"), "-i", destination, "-o", raw])
    require(raw.stat().st_size == lock["raw_size"] and digest_file(raw, ("sha256",))["sha256"] == lock["raw_sha256"],
            "The reference kernel payload differs from the frozen HC3 payload.")
    project.record("kernel", {"mode": "verified-local-reference", "image": str(destination),
                              "image_hashes": hashes, "raw_sha256": lock["raw_sha256"],
                              "clean_rebuild_complete": False})
    say("Exact HC3 local reference staged (development mode).", 'success')


def reference(project: Project) -> Path:
    stage = project.stage("kernel")
    lock = load_json(project.root / "profiles/kernel-reference.json")
    path = Path(stage["image"])
    require(stage['mode'] in {'verified-local-reference', 'source-rebuilt'}, 'Unknown staged kernel mode.')
    expected = stage['image_hashes']['sha256'] if stage['mode'] == 'source-rebuilt' else lock['image_sha256']
    require(path.is_file() and digest_file(path, ("sha256",))["sha256"] == expected, "Staged kernel reference changed.")
    if stage['mode'] == 'source-rebuilt':
        import hashlib
        require(stage.get('clean_rebuild_complete') and stage['raw_sha256'] == lock['raw_sha256'] and
                hashlib.sha256(split_image(path.read_bytes())[0]).hexdigest() == lock['im4p_sha256'],
                'Source-built kernel acceptance record changed.')
    return path

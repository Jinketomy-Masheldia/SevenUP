"""Pinned IPSW validation and path-safe, atomic resource extraction."""

from __future__ import annotations

from .console import say

import hashlib
import plistlib
import shutil
import tempfile
import zipfile
from pathlib import Path, PurePosixPath

from .core import Project, PortError, digest_file, load_json, publish_directory, require, save_json


def select_identity(manifest: dict, model: str) -> dict:
    matches = [identity for identity in manifest.get("BuildIdentities", [])
               if identity.get("Info", {}).get("DeviceClass", "").lower() == model.lower()
               and identity.get("Info", {}).get("RestoreBehavior") == "Erase"
               and "Customer" in identity.get("Info", {}).get("Variant", "")]
    require(len(matches) == 1, f"Expected exactly one customer erase BuildIdentity for {model}; found {len(matches)}.")
    return matches[0]


def safe_member(name: str) -> str:
    path = PurePosixPath(name)
    require(bool(name) and not path.is_absolute() and ".." not in path.parts and "\\" not in name,
            f"Unsafe ZIP path: {name!r}")
    return str(path)


def locate_sources(project: Project, *, allow_missing=False) -> dict:
    directory = project.root / "inputs/ipsw"
    result = {}
    for source in project.sources:
        path = directory / source["filename"]
        if path.is_file():
            result[source["role"]] = path
        elif source["required"]:
            say(f"MISSING: {source['filename']}", 'error')
    missing = [s["role"] for s in project.sources if s["required"] and s["role"] not in result]
    require(allow_missing or not missing, f"Missing required IPSWs. Place them in {directory} and run 'prepare' again.")
    return result


def verify_source(path: Path, source: dict) -> tuple[dict, dict]:
    require(path.stat().st_size == source["size"], f"Unexpected IPSW size: {path.name}")
    say(f"Checking MD5, SHA1, and recording SHA256: {path.name}", 'info')
    hashes = digest_file(path)
    require(hashes["md5"] == source["md5"] and hashes["sha1"] == source["sha1"],
            f"IPSW checksum mismatch: {path.name}. The archive was not extracted.")
    try:
        with zipfile.ZipFile(path) as archive:
            manifests = [entry for entry in archive.infolist() if entry.filename == "BuildManifest.plist"]
            require(len(manifests) == 1 and manifests[0].file_size < 16 * 1024 * 1024, "Invalid BuildManifest entry.")
            manifest = plistlib.loads(archive.read(manifests[0]))
    except (zipfile.BadZipFile, plistlib.InvalidFileException) as exc:
        raise PortError(f"Invalid IPSW archive: {path.name}") from exc
    validate_manifest(manifest, source)
    return hashes, manifest


def validate_manifest(manifest: dict, source: dict):
    require(manifest.get("ProductVersion") == source["version"] and manifest.get("ProductBuildVersion") == source["build"],
            f"BuildManifest version does not match the pinned source: {source['role']}")
    require(source["product"] in manifest.get("SupportedProductTypes", []), f"Wrong product in {source['role']}")
    select_identity(manifest, source["model"])


def component_paths(manifest: dict, source: dict, available: set[str]) -> dict:
    identity = select_identity(manifest, source["model"])
    names = ["iBSS", "iBEC", "DeviceTree", "KernelCache", "RestoreRamDisk", "RestoreTrustCache"]
    if source["role"] in {"ipad_target", "iphone8_donor"}:
        names += ["OS", "Cryptex1,SystemOS", "Cryptex1,AppOS"]
    selected = {}
    for key in names:
        entry = identity.get("Manifest", {}).get(key)
        if entry:
            member = safe_member(entry["Info"]["Path"])
            require(member in available, f"BuildManifest refers to missing member: {member}")
            selected[key] = member
    for mandatory in ["iBSS", "iBEC", "DeviceTree", "KernelCache", "RestoreRamDisk"]:
        require(mandatory in selected, f"Missing required component {mandatory} for {source['role']}")
    if "RestoreTrustCache" not in selected:
        ramdisk = selected["RestoreRamDisk"]
        candidates = [ramdisk + ".trustcache", "Firmware/" + ramdisk + ".trustcache"]
        found = [name for name in candidates if name in available]
        require(len(found) == 1, "Cannot uniquely identify the RestoreRamDisk trustcache.")
        selected["RestoreTrustCache"] = found[0]
    if source["role"] in {"ipad_target", "iphone8_donor"}:
        require(all(key in selected for key in ["OS", "Cryptex1,SystemOS", "Cryptex1,AppOS"]),
                "The rootfs and both Cryptex images are required for this profile.")
    return selected


def extract_source(project: Project, path: Path, source: dict, hashes: dict, manifest: dict) -> dict:
    destination = project.work / "extracted" / source["role"]
    with zipfile.ZipFile(path) as archive:
        available = {entry.filename for entry in archive.infolist()}
        paths = component_paths(manifest, source, available)
        needed = set(paths.values()) | {"BuildManifest.plist"}
        if destination.exists():
            receipt = load_json(destination / "resources.json")
            require(receipt.get("archive_hashes", hashes) == hashes, "Existing extracted source comes from a different IPSW.")
            require(receipt["components"] == paths and set(receipt["files"]) == needed,
                    "Existing extracted component set differs from the pinned IPSW.")
            for name, record in receipt["files"].items():
                safe_member(name)
                require(digest_file(destination / name, ("sha256",))["sha256"] == record["sha256"], f"Extracted file changed: {name}")
            if "archive_hashes" not in receipt:
                require(receipt["files"]["BuildManifest.plist"]["sha256"] ==
                        hashlib.sha256(archive.read("BuildManifest.plist")).hexdigest(),
                        "Cached partial-download manifest differs from the complete IPSW.")
                receipt["archive_hashes"] = hashes
                receipt["full_archive_verified"] = True
                save_json(destination / "resources.json", receipt)
            return receipt
        total = sum(archive.getinfo(name).file_size for name in needed)
        require(shutil.disk_usage(project.root).free >= total + 512 * 1024 * 1024,
                f"Insufficient free space to extract {source['role']}; need {total // 1024**2 + 512} MiB.")
        parent = destination.parent
        parent.mkdir(parents=True, exist_ok=True)
        staging = Path(tempfile.mkdtemp(prefix=".extract-", dir=parent))
        try:
            files = {}
            for name in sorted(needed):
                safe_member(name)
                info = archive.getinfo(name)
                require(((info.external_attr >> 16) & 0o170000) != 0o120000, "ZIP symlinks are not accepted.")
                require(sum(item.filename == name for item in archive.infolist()) == 1, f"Duplicate ZIP member: {name}")
                target = staging / name
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(info) as src, target.open("xb") as dst:
                    shutil.copyfileobj(src, dst, 8 * 1024 * 1024)
                require(target.stat().st_size == info.file_size, f"Incomplete extraction: {name}")
                files[name] = {"size": info.file_size, **digest_file(target, ("sha256",))}
            receipt = {"role": source["role"], "archive_hashes": hashes, "model": source["model"],
                       "version": source["version"], "build": source["build"], "components": paths, "files": files}
            save_json(staging / "resources.json", receipt)
            publish_directory(staging, destination)
            return receipt
        except BaseException:
            shutil.rmtree(staging, ignore_errors=True)
            raise


def prepare(project: Project, *, extract=True, allow_missing=False):
    project.initialize()
    located = locate_sources(project, allow_missing=allow_missing)
    report = {}
    for source in project.sources:
        if source["role"] not in located:
            continue
        path = located[source["role"]]
        hashes, manifest = verify_source(path, source)
        report[source["role"]] = {"path": str(path), "hashes": hashes, "build": source["build"]}
        if extract and (source["required"] or source.get("automatic_components")):
            extract_source(project, path, source, hashes, manifest)
        say(f"VERIFIED: {source['role']} / {source['version']} / {source['build']}", 'success')
    project.record("resources", {"sources": report, "extracted": extract,
                                 "complete": all(not s["required"] or s["role"] in report for s in project.sources)})
    return report


def fetch_bootstrap(project: Project) -> dict:
    """Fetch only the 15.6 SSHRD components, as the upstream builder does.

    A full 15.6 IPSW is optional. Partial downloads are checked against a pinned
    BuildManifest and its component digests; no full-IPSW MD5 claim is made.
    pzb strips output directory prefixes, so every download uses a private cwd.
    """
    project.initialize()
    source = next(row for row in project.sources if row["role"] == "iphone7_bootstrap")
    destination = project.work / "extracted" / source["role"]
    if destination.exists():
        record = load_json(destination / "resources.json")
        for name in ["iBSS", "iBEC", "DeviceTree", "KernelCache", "RestoreRamDisk", "RestoreTrustCache"]:
            resource(project, source["role"], name)
        say("Using verified cached 15.6 SSHRD components.", 'success')
        return record
    archive = project.root / "inputs/ipsw" / source["filename"]
    if archive.is_file():
        hashes, manifest = verify_source(archive, source)
        return extract_source(project, archive, source, hashes, manifest)
    require(shutil.disk_usage(project.root).free >= 1024**3, "At least 1 GiB of free space is required for bootstrap preparation.")
    parent = destination.parent
    parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".bootstrap-", dir=parent))
    try:
        say("Fetching only the pinned 15.6 SSHRD components; a full 15.6 IPSW is not required.", 'info')
        project.run([project.tool("pzb"), "-g", "BuildManifest.plist", source["url"]], cwd=staging, timeout=300)
        path = staging / "BuildManifest.plist"
        require(path.is_file() and path.stat().st_size < 16 * 1024**2, "Bootstrap BuildManifest is missing or too large.")
        require(digest_file(path, ("sha256",))["sha256"] == source["manifest_sha256"], "Bootstrap BuildManifest checksum mismatch.")
        manifest = plistlib.loads(path.read_bytes())
        validate_manifest(manifest, source)
        identity = select_identity(manifest, source["model"])
        paths = {key: safe_member(identity["Manifest"][key]["Info"]["Path"])
                 for key in ["iBSS", "iBEC", "DeviceTree", "KernelCache", "RestoreRamDisk", "RestoreTrustCache"]}
        files = {"BuildManifest.plist": {"size": path.stat().st_size, **digest_file(path, ("sha256",))}}
        for index, (name, member) in enumerate(paths.items()):
            temporary = f"component-{index}.download"
            project.run([project.tool("pzb"), "-g", member, "-o", temporary, source["url"]], cwd=staging, timeout=600)
            downloaded = staging / temporary
            require(downloaded.is_file() and 0 < downloaded.stat().st_size < 768 * 1024**2, f"Invalid downloaded component: {name}")
            expected = identity["Manifest"][name].get("Digest")
            algorithm = {20: "sha1", 32: "sha256", 48: "sha384"}.get(len(expected) if isinstance(expected, bytes) else 0)
            require(algorithm is not None, f"Unsupported manifest digest for {name}.")
            actual = digest_file(downloaded, (algorithm,))[algorithm]
            require(actual == expected.hex(), f"BuildManifest component digest mismatch: {name}")
            target = staging / member
            target.parent.mkdir(parents=True, exist_ok=True)
            downloaded.rename(target)
            files[member] = {"size": target.stat().st_size, **digest_file(target, ("sha256",))}
        record = {"role": source["role"], "validation": "pinned-manifest-and-component-digests",
                  "full_archive_verified": False, "source_url": source["url"],
                  "model": source["model"], "version": source["version"], "build": source["build"],
                  "components": paths, "files": files}
        save_json(staging / "resources.json", record)
        publish_directory(staging, destination)
        project.record("bootstrap-resources", {"folder": str(destination), "validation": record["validation"]})
        return record
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def resource(project: Project, role: str, name: str) -> Path:
    directory = project.work / "extracted" / role
    require((directory / "resources.json").exists(), f"Resources are not extracted for {role}. Run 'prepare'.")
    record = load_json(directory / "resources.json")
    require(name in record["components"], f"Missing component {name} in {role}.")
    member = record["components"][name]
    path = directory / safe_member(member)
    require(digest_file(path, ("sha256",))["sha256"] == record["files"][member]["sha256"], f"Resource changed: {role}/{name}")
    return path

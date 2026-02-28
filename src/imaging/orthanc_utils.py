"""Orthanc DICOM server helper utilities.

Mirrors the helper functions from WELCOME.ipynb, promoted to a proper module.
Credentials are read from environment variables (see .env.example).

Defaults match the hackathon Orthanc instance:
    URL  : http://10.0.1.215:8042
    user : unboxed
    pass : unboxed2026
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import requests

# ---------------------------------------------------------------------------
# Connection settings (from env, with notebook defaults)
# ---------------------------------------------------------------------------
ORTHANC_URL: str = os.getenv("ORTHANC_URL", "http://10.0.1.215:8042")
ORTHANC_USER: str = os.getenv("ORTHANC_USER", "unboxed")
ORTHANC_PASS: str = os.getenv("ORTHANC_PASS", "unboxed2026")


def _auth() -> tuple[str, str]:
    return (ORTHANC_USER, ORTHANC_PASS)


# ---------------------------------------------------------------------------
# Upload
# ---------------------------------------------------------------------------

def upload_dicom(path: str | Path) -> str | None:
    """Upload a single .dcm file to Orthanc.

    Returns the Orthanc instance ID on success, None on failure.
    (Same as upload_dicom() in WELCOME.ipynb.)
    """
    with open(path, "rb") as f:
        r = requests.post(
            f"{ORTHANC_URL}/instances",
            auth=_auth(),
            data=f.read(),
            headers={"Content-Type": "application/dicom"},
            timeout=30,
        )
    if r.status_code == 200:
        iid = r.json().get("ID")
        print(f"  ✅ Upload OK  →  instance ID : {iid}")
        return iid
    print(f"  ❌ Erreur {r.status_code} : {r.text}")
    return None


def upload_dicom_folder(folder: str | Path) -> dict[str, int]:
    """Upload all .dcm files in *folder* (recursive) to Orthanc.

    Returns ``{"ok": n, "errors": m}``.
    (Same as upload_dicom_folder() in WELCOME.ipynb.)
    """
    files = list(Path(folder).rglob("*.dcm"))
    print(f"  📂 {len(files)} fichier(s) .dcm trouvé(s) dans '{folder}'")
    ok = err = 0
    for f in files:
        with open(f, "rb") as fh:
            r = requests.post(
                f"{ORTHANC_URL}/instances",
                auth=_auth(),
                data=fh.read(),
                headers={"Content-Type": "application/dicom"},
                timeout=30,
            )
        if r.status_code == 200:
            print(f"  ✅  {f.name}")
            ok += 1
        else:
            print(f"  ❌  {f.name}  (HTTP {r.status_code})")
            err += 1
    print(f"  Résultat : {ok} OK · {err} erreur(s)")
    return {"ok": ok, "errors": err}


# ---------------------------------------------------------------------------
# Download
# ---------------------------------------------------------------------------

def download_study(
    study_id: str,
    out_dir: str | Path = "/home/jovyan/work",
) -> str:
    """Download a complete study (.zip archive) from Orthanc.

    Returns the path of the saved zip file.
    (Same as download_study() in WELCOME.ipynb.)
    """
    dest = Path(out_dir) / f"study_{study_id[:8]}.zip"
    dest.parent.mkdir(parents=True, exist_ok=True)
    print(f"  ⬇️  Téléchargement de l'étude {study_id[:12]}…")
    with requests.get(
        f"{ORTHANC_URL}/studies/{study_id}/archive",
        auth=_auth(),
        stream=True,
        timeout=120,
    ) as r:
        r.raise_for_status()
        total = 0
        with open(dest, "wb") as f:
            for chunk in r.iter_content(8192):
                f.write(chunk)
                total += len(chunk)
    print(f"  ✅ Sauvegardé : {dest}  ({total / 1e6:.1f} Mo)")
    return str(dest)


# ---------------------------------------------------------------------------
# List studies
# ---------------------------------------------------------------------------

def list_studies() -> list[dict[str, Any]]:
    """Return a list of study-level metadata dicts from Orthanc."""
    study_ids: list[str] = requests.get(
        f"{ORTHANC_URL}/studies", auth=_auth(), timeout=10
    ).json()
    rows: list[dict[str, Any]] = []
    for sid in study_ids:
        info = requests.get(
            f"{ORTHANC_URL}/studies/{sid}", auth=_auth(), timeout=10
        ).json()
        t = info.get("MainDicomTags", {})
        rows.append({
            "study_id":   sid,
            "patient_id": t.get("PatientID", ""),
            "study_date": t.get("StudyDate", ""),
            "description": t.get("StudyDescription", ""),
            "modalities": t.get("ModalitiesInStudy", ""),
        })
    return rows

from pathlib import Path

import pytest
from backend.scripts.apply_blno_mongo import (
    build_upsert_filter,
    load_bundle,
    override_academy_id,
    validate_write_request,
)


def test_build_upsert_filter_uses_collection_identity() -> None:
    assert build_upsert_filter("users", {"email": "parent@example.com", "user_id": "user_1"}) == {
        "email": "parent@example.com"
    }
    assert build_upsert_filter("students", {"student_id": "stu_1"}) == {"student_id": "stu_1"}
    assert build_upsert_filter("academy_memberships", {"membership_id": "mem_1"}) == {
        "membership_id": "mem_1"
    }
    assert build_upsert_filter(
        "platform_roles", {"user_id": "user_1", "role": "platform_admin"}
    ) == {
        "user_id": "user_1",
        "role": "platform_admin",
    }
    assert build_upsert_filter(
        "waiver_acceptances",
        {"academy_id": "acad_1", "student_id": "stu_1", "waiver_version_id": "1.0"},
    ) == {
        "academy_id": "acad_1",
        "student_id": "stu_1",
        "waiver_version_id": "1.0",
    }


def test_validate_write_request_requires_apply_and_production_confirmation() -> None:
    validate_write_request(
        target="local",
        mongo_url="mongodb://127.0.0.1:27017",
        apply=True,
        confirm_production=None,
        academy_id="acad_blno_badminton",
    )

    with pytest.raises(SystemExit, match="Refusing local write"):
        validate_write_request(
            target="local",
            mongo_url="mongodb+srv://cluster.example/db",
            apply=True,
            confirm_production=None,
            academy_id="acad_blno_badminton",
        )

    with pytest.raises(SystemExit, match="requires --confirm-production"):
        validate_write_request(
            target="production",
            mongo_url="mongodb+srv://cluster.example/db",
            apply=True,
            confirm_production=None,
            academy_id="acad_blno_badminton",
        )

    validate_write_request(
        target="production",
        mongo_url="mongodb+srv://cluster.example/db",
        apply=True,
        confirm_production="acad_blno_badminton",
        academy_id="acad_blno_badminton",
    )


def test_load_bundle_requires_manifest_and_collections(tmp_path: Path) -> None:
    bundle_path = tmp_path / "bundle.json"
    bundle_path.write_text(
        '{"manifest":{"academy_id":"acad_blno_badminton"},"collections":{"students":[]}}'
    )

    bundle = load_bundle(bundle_path)

    assert bundle["manifest"]["academy_id"] == "acad_blno_badminton"
    assert bundle["collections"]["students"] == []


def test_override_academy_id_updates_manifest_and_documents() -> None:
    bundle = {
        "manifest": {"academy_id": "acad_blno_badminton"},
        "collections": {
            "academies": [{"academy_id": "acad_blno_badminton", "display_name": "BLNO"}],
            "students": [{"academy_id": "acad_blno_badminton", "student_id": "stu_1"}],
            "users": [{"academy_id": "acad_blno_badminton", "user_id": "user_1"}],
        },
    }

    overridden = override_academy_id(bundle, "default-academy")

    assert overridden["manifest"]["academy_id"] == "default-academy"
    assert overridden["collections"]["academies"][0]["academy_id"] == "default-academy"
    assert overridden["collections"]["students"][0]["academy_id"] == "default-academy"
    assert overridden["collections"]["users"][0]["academy_id"] == "default-academy"

"""Unit tests for student_progress domain pure functions."""

from __future__ import annotations

from backend.v2.contexts.student_progress.domain.logic import (
    calculate_skill_pass,
    check_level_completion,
    generate_cert_number,
)


def test_calculate_skill_pass_basic():
    # 7 successes out of 10 attempts at 70% threshold → True
    assert calculate_skill_pass(10, 7, 70.0) is True


def test_calculate_skill_pass_boundary():
    # exactly at threshold: 7/10 = 70% → True
    assert calculate_skill_pass(10, 7, 70.0) is True


def test_calculate_skill_pass_above_threshold():
    # 9/10 = 90% at 70% threshold → True
    assert calculate_skill_pass(10, 9, 70.0) is True


def test_calculate_skill_pass_below_threshold():
    # 6/10 = 60% at 70% threshold → False
    assert calculate_skill_pass(10, 6, 70.0) is False


def test_calculate_skill_pass_zero_attempts():
    # no attempts → False (cannot pass without data)
    assert calculate_skill_pass(0, 0, 70.0) is False


def test_calculate_skill_pass_perfect():
    # 10/10 = 100% → True at any reasonable threshold
    assert calculate_skill_pass(10, 10, 100.0) is True


def test_calculate_skill_pass_zero_successes():
    # 0/5 = 0% → False
    assert calculate_skill_pass(5, 0, 70.0) is False


def test_check_level_completion_all_required():
    # all required skills passed → True
    assert check_level_completion(["s1", "s2"], {"s1", "s2"}) is True


def test_check_level_completion_optional_excluded():
    # optional skill not in required list; only required ones count
    assert check_level_completion(["s1"], {"s1"}) is True


def test_check_level_completion_not_ready():
    # one required skill missing → False
    assert check_level_completion(["s1", "s2"], {"s1"}) is False


def test_check_level_completion_empty_required():
    # level has no required skills → True (trivially met)
    assert check_level_completion([], set()) is True


def test_check_level_completion_extra_passed():
    # extra passed skills beyond required are fine
    assert check_level_completion(["s1"], {"s1", "s2", "s3"}) is True


def test_generate_cert_number_format():
    cert = generate_cert_number("acad123", "stud456", 3, 1717613400000)
    # should be a non-empty string
    assert isinstance(cert, str)
    assert len(cert) > 0


def test_generate_cert_number_contains_level():
    cert = generate_cert_number("acad123", "stud456", 3, 1717613400000)
    assert "L3" in cert


def test_generate_cert_number_contains_academy_prefix():
    cert = generate_cert_number("acad123", "stud456", 3, 1717613400000)
    # first 3 chars of academy_id uppercased
    assert "ACA" in cert


def test_generate_cert_number_contains_student_suffix():
    cert = generate_cert_number("acad123", "stud456", 3, 1717613400000)
    # last 4 chars of student_id uppercased
    assert "D456" in cert


def test_generate_cert_number_different_levels():
    cert1 = generate_cert_number("acad123", "stud456", 1, 1717613400000)
    cert2 = generate_cert_number("acad123", "stud456", 6, 1717613400000)
    assert cert1 != cert2
    assert "L1" in cert1
    assert "L6" in cert2

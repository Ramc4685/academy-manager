"""Unit tests for student_progress domain pure functions."""

from __future__ import annotations

from backend.v2.contexts.student_progress.domain.logic import (
    calculate_skill_pass,
    check_level_completion,
    format_cert_number,
)


def test_calculate_skill_pass_basic():
    # 7 successes out of 10 attempts at 70% threshold → True
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


def test_format_cert_number_uses_the_academy_prefix():
    assert format_cert_number("BLNO", 42) == "BLNO-C-0042"
    assert format_cert_number("BLNO", 12345) == "BLNO-C-12345"


def test_format_cert_number_without_a_prefix_borrows_none():
    assert format_cert_number(None, 7) == "C-0007"
    assert format_cert_number("", 7) == "C-0007"

"""Tests for IM review policy helper."""

from packages.outreach_policy import workflow_im_review_required


def test_workflow_im_review_required_false_by_default():
    assert workflow_im_review_required({}) is False
    assert workflow_im_review_required({"outreach": {}}) is False
    assert workflow_im_review_required({"outreach": {"im_review_required": False}}) is False


def test_workflow_im_review_required_true():
    assert workflow_im_review_required({"outreach": {"im_review_required": True}}) is True

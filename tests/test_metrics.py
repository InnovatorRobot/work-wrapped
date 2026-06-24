from metrics.jira import _jira_metrics
from metrics.gerrit import _gerrit_metrics, _gerrit_changes_to_commits


def test_jira_metrics_counts():
    jira = [
        {
            "status": "In Review",
            "was_reopened": True,
            "comment_count": 3,
            "story_points": 5,
            "resolutiondate": "2026-06-01",
            "days_in_todo": 2,
        },
        {"status": "Blocked", "comment_count": 1, "days_in_todo": 4},
        {"status": "Done", "comment_count": 2, "story_points": 8, "resolutiondate": "2026-06-02"},
    ]
    m = _jira_metrics(jira)
    assert m["in_review_count"] == 1
    assert m["blocked_count"] == 1
    assert m["reopened_count"] == 1
    assert m["comments_per_ticket_avg"] == round((3 + 1 + 2) / 3, 1)
    assert m["story_points_done"] == 13  # 5 + 8 (both resolved)
    assert m["avg_days_in_todo"] == 3.0


def test_gerrit_topic_and_rework():
    gerrit = [
        {
            "status": "MERGED",
            "topic": "oauth",
            "patch_sets": 4,
            "project": "p",
            "month": "2026-06",
            "number": 1,
            "insertions": 1,
            "deletions": 1,
        },
        {
            "status": "MERGED",
            "topic": "oauth",
            "patch_sets": 1,
            "project": "p",
            "month": "2026-06",
            "number": 2,
            "insertions": 1,
            "deletions": 0,
        },
        {
            "status": "NEW",
            "topic": "refactor",
            "patch_sets": 7,
            "project": "p",
            "month": "2026-06",
            "number": 3,
            "insertions": 5,
            "deletions": 2,
        },
    ]
    m = _gerrit_metrics(gerrit)
    topics = dict(m["top_topics"])
    assert topics["oauth"] == 2
    assert topics["refactor"] == 1
    assert m["avg_patch_sets"] == round((4 + 1 + 7) / 3, 1)
    assert m["changes_with_rework"] == 2
    assert m["max_patch_sets"] == 7


def test_gerrit_changes_to_commits_extracts_topic_and_patch_sets():
    changes = [
        {
            "subject": "Fix bug",
            "project": "proj",
            "created": "2026-06-01 10:00:00.000000000",
            "status": "MERGED",
            "topic": "mytopic",
            "_number": 42,
            "revisions": {"a": {}, "b": {}, "c": {}},
        }
    ]
    commits = _gerrit_changes_to_commits(changes)
    assert commits[0]["topic"] == "mytopic"
    assert commits[0]["patch_sets"] == 3

from sentinel import activity_learning


def test_weighted_task_similarity_gives_rare_terms_more_influence():
    common_term = activity_learning.weighted_jaccard(
        ["python", "automation"], ["python", "notes"],
        document_frequency={"python": 20, "automation": 1, "notes": 1},
        document_count=20,
    )
    rare_term = activity_learning.weighted_jaccard(
        ["python", "automation"], ["python", "notes"],
        document_frequency={"python": 1, "automation": 1, "notes": 1},
        document_count=20,
    )
    assert 0.0 < common_term < rare_term <= 1.0

def test_task_candidate_ranking_prefers_recent_semantically_close_cluster():
    candidates = [
        {"id": 1, "terms": ["python", "automation"], "observations": 4, "last_seen": 100.0},
        {"id": 2, "terms": ["python", "music"], "observations": 8, "last_seen": 999.0},
    ]
    ranked = activity_learning.rank_task_candidates(
        ["python", "automation", "scheduler"], candidates, now=1000.0
    )
    assert ranked
    assert ranked[0][1]["id"] == 1
    assert ranked[0][0] > ranked[-1][0]


def test_routine_confidence_penalizes_competing_next_app_choices():
    unambiguous, unambiguous_probability = activity_learning.routine_confidence(
        observations=8, total_observations=8, alternatives=1, age_days=0, hour_distance=0
    )
    contested, contested_probability = activity_learning.routine_confidence(
        observations=8, total_observations=16, alternatives=2, age_days=0, hour_distance=0
    )
    assert unambiguous_probability > contested_probability
    assert unambiguous > contested


def test_routine_confidence_decays_with_stale_evidence_and_time_mismatch():
    recent, _ = activity_learning.routine_confidence(10, 10, 1, 0, 0)
    stale, _ = activity_learning.routine_confidence(10, 10, 1, 90, 3)
    assert recent > stale


def test_hour_distance_wraps_at_midnight():
    assert activity_learning.hour_distance(23, 1) == 2
    assert activity_learning.hour_distance(1, 23) == 2
    assert activity_learning.hour_distance(9, 9) == 0

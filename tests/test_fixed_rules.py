from pinendar.domain.fixed_rules import fixed_rule_load_error, partition_fixed_rule_load


def test_one_of_alternatives_does_not_sum_their_loads() -> None:
    assert (
        fixed_rule_load_error(
            required_mode="one",
            required_ids=["a", "b", "c"],
            peonada_ids=[],
            occurrences={item: {1, 2, 3, 4, 5} for item in ("a", "b", "c")},
            loads={"a": 100, "b": 100, "c": 100},
        )
        is None
    )


def test_peonada_split_must_be_exact_for_every_recurrence_combination() -> None:
    error = fixed_rule_load_error(
        required_mode="all",
        required_ids=["weekly-half", "monthly-half", "monthly-full"],
        peonada_ids=["monthly-full"],
        occurrences={
            "weekly-half": {1, 2, 3, 4, 5},
            "monthly-half": {1},
            "monthly-full": {1, 2},
        },
        loads={"weekly-half": 50, "monthly-half": 50, "monthly-full": 100},
    )

    assert error is not None
    assert "exactament 100%" in error


def test_configured_peonada_is_ordinary_when_there_is_no_overload() -> None:
    partition = partition_fixed_rule_load(
        ["configured-peonada"],
        {"configured-peonada"},
        {"configured-peonada": 100},
    )

    assert partition.ordinary_ids == ("configured-peonada",)
    assert partition.peonada_ids == ()

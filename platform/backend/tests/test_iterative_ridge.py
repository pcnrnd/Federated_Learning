"""G3-A: 독립한 한 step 손계산·mean/l2/bias·유한성·고정 입력 개선."""
from __future__ import annotations

import copy
from fractions import Fraction

import pytest

from silo_sdk.iterative_ridge import ridge_objective, train_iterative_ridge
from silo_sdk.trainer import train_ridge

ROWS = [{"x": 1, "y": 2}, {"x": 3, "y": 4}]


def train(rows=ROWS, **overrides):
    settings = {"initial_parameters": [0.5, -1], "l2": 0.2, "step_size": 0.1, "steps": 1}
    return train_iterative_ridge(rows, ["x"], "y", **{**settings, **overrides})


def test_one_step_matches_independent_fraction_hand_calculation_and_flattening():
    # residuals=(-5/2,-7/2), grad_w=(-5/2-21/2)/2+1/10=-32/5, grad_b=-3.
    expected = [Fraction(1, 2) - Fraction(1, 10) * Fraction(-32, 5),
                -1 - Fraction(1, 10) * -3]
    answer = train()
    assert answer.parameters == pytest.approx([float(p) for p in expected])
    assert answer.parameters == pytest.approx([1.14, -0.7])  # [weight, bias]
    assert answer.initial_objective == pytest.approx(4.65)
    assert answer.objective == pytest.approx(1.14796)
    assert answer.sample_count == 2 and answer.steps == 1


def test_initial_global_parameters_change_the_finite_step_and_inputs_are_preserved():
    rows, initial = copy.deepcopy(ROWS), [0.5, -1.0]
    first = train(rows, initial_parameters=initial)
    second = train(rows, initial_parameters=[0, 0])
    assert first.parameters != second.parameters
    assert rows == ROWS and initial == [0.5, -1.0]
    assert first.rows_seen == first.sample_count == 2 and first.rows_excluded == 0


def test_mean_loss_and_regularization_are_unchanged_when_all_rows_are_repeated():
    once = train()
    repeated = train(ROWS * 5)
    assert repeated.parameters == pytest.approx(once.parameters)
    assert repeated.initial_objective == pytest.approx(once.initial_objective)
    assert repeated.objective == pytest.approx(once.objective)
    assert repeated.sample_count == 10


def test_bias_is_unpenalized_while_weight_receives_l2_gradient():
    data = [{"x": 0, "y": 5}, {"x": 0, "y": 5}]
    penalized = train(data, initial_parameters=[2, 0], l2=3)
    loose = train(data, initial_parameters=[2, 0], l2=0)
    assert penalized.initial_objective == pytest.approx(18.5)
    assert penalized.parameters == pytest.approx([1.4, 0.5])
    assert loose.parameters == pytest.approx([2, 0.5])


def test_feature_order_is_preserved_and_bias_is_last():
    # x=[2,1], w=[1,3], b=0 → residual=5; gradients=[10,5,5].
    answer = train_iterative_ridge([{"a": 1, "b": 2, "y": 0}], ["b", "a"], "y",
        initial_parameters=[1, 3, 0], l2=0, step_size=0.1, steps=1)
    assert answer.parameters == pytest.approx([0, 2.5, -0.5])


def test_fixed_stable_input_improves_loss_and_matches_independent_analytic_optimum():
    # mean-loss ridge optimum: w=(2/3)/(2/3+2)=1/4, b=10; J*=1/4.
    data = [{"x": -1, "y": 9}, {"x": 0, "y": 10}, {"x": 1, "y": 11}]
    answer = train(data, initial_parameters=[0, 0], l2=2, step_size=0.2, steps=300)
    assert answer.parameters == pytest.approx([0.25, 10], abs=1e-10)
    assert answer.objective == pytest.approx(0.25)
    assert answer.objective < answer.initial_objective
    assert ridge_objective(data, ["x"], "y", answer.parameters, l2=2) == answer.objective
    # 기존 closed form의 sum-loss lambda는 n*l2로 맞춰야 같은 optimum이다.
    assert train_ridge(data, ["x"], "y", l2=len(data) * 2).parameters == pytest.approx(answer.parameters)


def test_invalid_rows_are_excluded_from_the_actual_sample_count():
    bad = [{"x": None, "y": 1}, {"x": True, "y": 1}, {"x": "bad", "y": 1},
           {"x": float("nan"), "y": 1}, {"x": 1, "y": float("inf")}, [1, 2]]
    answer = train([*ROWS, {"x": "1", "y": "2"}, *bad])
    assert answer.sample_count == 3 and answer.rows_seen == 9 and answer.rows_excluded == 6


@pytest.mark.parametrize("configuration", [
    {"l2": -1}, {"l2": float("nan")}, {"l2": float("inf")}, {"l2": True},
    {"step_size": 0}, {"step_size": -1}, {"step_size": float("inf")}, {"step_size": "0.1"},
    {"steps": 0}, {"steps": 1.2}, {"steps": True},
    {"initial_parameters": []}, {"initial_parameters": [1]}, {"initial_parameters": [1, 2, 3]},
    {"initial_parameters": [float("inf"), 0]}, {"initial_parameters": [0, float("nan")]},
    {"initial_parameters": [True, 0]}, {"initial_parameters": None},
])
def test_invalid_solver_configuration_or_global_model_is_rejected(configuration):
    with pytest.raises(ValueError):
        train(**configuration)


@pytest.mark.parametrize("features,target", [([], "y"), (["x", "x"], "y"),
    ([""], "y"), (["x"], "x"), (["x"], ""), ("x", "y")])
def test_invalid_model_space_is_rejected(features, target):
    with pytest.raises(ValueError):
        train_iterative_ridge(ROWS, features, target, initial_parameters=[0, 0],
                              l2=0, step_size=0.1, steps=1)


@pytest.mark.parametrize("rows", [[], [{"x": float("nan"), "y": 1}], None])
def test_empty_or_unusable_input_is_rejected(rows):
    with pytest.raises(ValueError):
        train(rows)


def test_nonfinite_prediction_objective_or_update_never_returns_a_model():
    with pytest.raises(ValueError):
        train([{"x": 1e200, "y": 1}], initial_parameters=[1, 0])
    with pytest.raises(ValueError):
        train([{"x": 1e150, "y": 1}], initial_parameters=[0, 0], step_size=1e200)

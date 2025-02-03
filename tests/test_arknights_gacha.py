import pytest
import numpy as np
from src.services.gacha.arknights import ArknightsGachaCalculator

def test_gacha_rates():
    """Test basic gacha rates calculation"""
    calculator = ArknightsGachaCalculator()
    
    # Test base rate
    assert calculator._calculate_single_pull_rate(0) == 0.02
    assert calculator._calculate_single_pull_rate(49) == 0.02
    
    # Test pity increase
    assert calculator._calculate_single_pull_rate(50) == 0.02
    assert calculator._calculate_single_pull_rate(51) == 0.04
    
    # Test rate cap
    assert calculator._calculate_single_pull_rate(98) >= 0.98  # Should be at least 98%
    assert calculator._calculate_single_pull_rate(99) == 1.0  # Must be 100% at pity 99

def test_banner_probability():
    """Test banner probability calculations"""
    calculator = ArknightsGachaCalculator()
    
    # Test normal banner (50% rate-up)
    result = calculator.calculate_banner_probability(pulls=50, is_limited=False)
    assert 0 <= result['probability'] <= 1
    assert result['expected_6stars'] >= 0
    assert result['expected_target'] >= 0
    assert np.isclose(result['expected_target'], result['expected_6stars'] * 0.5, rtol=1e-10)
    
    # Test limited banner (35% rate-up)
    result = calculator.calculate_banner_probability(pulls=50, is_limited=True)
    assert 0 <= result['probability'] <= 1
    assert result['expected_6stars'] >= 0
    assert result['expected_target'] >= 0
    assert np.isclose(result['expected_target'], result['expected_6stars'] * 0.35, rtol=1e-10)

def test_pity_system():
    """Test pity system mechanics"""
    calculator = ArknightsGachaCalculator()
    
    # Test guaranteed 6★ within 99 pulls
    result = calculator.calculate_banner_probability(pulls=99, is_limited=False)
    assert result['expected_6stars'] >= 1.0
    
    # Test expected value increases with more pulls
    result1 = calculator.calculate_banner_probability(pulls=50, is_limited=False)
    result2 = calculator.calculate_banner_probability(pulls=100, is_limited=False)
    assert result2['expected_6stars'] > result1['expected_6stars']

def test_resource_calculation():
    """Test resource to pull conversion"""
    calculator = ArknightsGachaCalculator()
    
    result = calculator.calculate_pulls_from_resources(
        orundum=6000,  # Should give 10 pulls
        originite=10,  # Should give 3 pulls
        permits=5
    )
    
    assert result['from_orundum'] == 10
    assert result['from_originite'] == 3
    assert result['from_permits'] == 5
    assert result['total_pulls'] == 18 
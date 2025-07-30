from typing import Dict, List, Tuple
import math

class GeneralGachaCalculator:
    """Calculator for general gacha probabilities without pity systems"""
    
    def __init__(self) -> None:
        """Initialize the general gacha calculator"""
        pass
    
    def calculate_probability(self, rate: float, attempts: int) -> Dict[str, float]:
        """Calculate probability of getting at least one desired item
        
        Args:
            rate: Pull rate as decimal (e.g., 0.0075 for 0.75%)
            attempts: Number of pull attempts
            
        Returns:
            Dict containing:
                'success_probability': Chance of getting at least one desired item
                'failure_probability': Chance of not getting the desired item
                'expected_successes': Expected number of successful pulls
                'rate_percent': The rate as percentage for display
        """
        # Validate inputs
        if rate <= 0 or rate > 1:
            raise ValueError("뽑기 확률은 0%보다 크고 100% 이하여야 해.")
        
        if attempts <= 0:
            raise ValueError("뽑기 횟수는 1회 이상이어야 해.")
        
        if attempts > 10000:
            raise ValueError("계산 가능한 최대 뽑기 횟수는 10,000회야.")
        
        # Calculate probabilities
        # Probability of failure in one pull
        failure_rate = 1 - rate
        
        # Probability of failure in all attempts
        total_failure_probability = failure_rate ** attempts
        
        # Probability of success (at least one success)
        success_probability = 1 - total_failure_probability
        
        # Expected number of successes
        expected_successes = attempts * rate
        
        # Convert rate to percentage for display
        rate_percent = rate * 100
        
        return {
            'success_probability': success_probability,
            'failure_probability': total_failure_probability,
            'expected_successes': expected_successes,
            'rate_percent': rate_percent
        }
    
    @staticmethod
    def calculate_attempts_for_probability(rate: float, desired_probability: float) -> int:
        """Calculate how many attempts needed to reach desired success probability
        
        Args:
            rate: Pull rate as decimal (e.g., 0.0075 for 0.75%)
            desired_probability: Desired success probability (e.g., 0.9 for 90%)
            
        Returns:
            Number of attempts needed
        """
        if rate <= 0 or rate >= 1:
            raise ValueError("뽑기 확률은 0%보다 크고 100%보다 작아야 해.")
        
        if desired_probability <= 0 or desired_probability >= 1:
            raise ValueError("목표 확률은 0%보다 크고 100%보다 작아야 해.")
        
        # Formula: attempts = log(1 - desired_probability) / log(1 - rate)
        attempts = math.log(1 - desired_probability) / math.log(1 - rate)
        
        return int(math.ceil(attempts))
    
    @staticmethod
    def _binomial_coefficient(n: int, k: int) -> float:
        """Calculate binomial coefficient C(n,k) = n! / (k! * (n-k)!)"""
        if k > n or k < 0:
            return 0.0
        if k == 0 or k == n:
            return 1.0
        
        # Use the more efficient formula to avoid large factorials
        result = 1.0
        for i in range(min(k, n - k)):
            result = result * (n - i) / (i + 1)
        return result
    
    @staticmethod
    def _binomial_probability(n: int, k: int, p: float) -> float:
        """Calculate P(X = k) for binomial distribution with n trials and probability p"""
        if p <= 0:
            return 1.0 if k == 0 else 0.0
        if p >= 1:
            return 1.0 if k == n else 0.0
            
        coeff = GeneralGachaCalculator._binomial_coefficient(n, k)
        return coeff * (p ** k) * ((1 - p) ** (n - k))
    
    @staticmethod
    def _binomial_probability_at_least(n: int, k: int, p: float) -> float:
        """Calculate P(X >= k) for binomial distribution"""
        if k <= 0:
            return 1.0
        if k > n:
            return 0.0
        
        # Sum from k to n
        total_prob = 0.0
        for i in range(k, n + 1):
            total_prob += GeneralGachaCalculator._binomial_probability(n, i, p)
        return total_prob
    
    def calculate_multi_character_probability(
        self, 
        characters: List[Tuple[str, float]], 
        attempts: int,
        target_counts: List[int] = None,
        at_least: bool = True
    ) -> Dict[str, any]:
        """Calculate probabilities for multiple characters with different rates
        
        Args:
            characters: List of (name, rate) tuples for each character
            attempts: Number of pull attempts
            target_counts: Target number of each character (None means at least 1)
            at_least: If True, calculate "at least X" probability, else "exactly X"
            
        Returns:
            Dict containing various probability scenarios
        """
        # Validate inputs
        if len(characters) < 2:
            raise ValueError("최소 2명의 캐릭터가 필요해.")
        
        if len(characters) > 5:
            raise ValueError("최대 5명의 캐릭터까지 계산 가능해.")
        
        if attempts <= 0:
            raise ValueError("뽑기 횟수는 1회 이상이어야 해.")
        
        if attempts > 5000:  # Lower limit for multi-character due to complexity
            raise ValueError("다중 캐릭터 계산시 최대 뽑기 횟수는 5,000회야.")
        
        for name, rate in characters:
            if rate <= 0 or rate > 1:
                raise ValueError(f"{name}의 풀 확률은 0%보다 크고 100% 이하여야 해.")
        
        # Set default target counts to 1 if not provided
        if target_counts is None:
            target_counts = [1] * len(characters)
        
        if len(target_counts) != len(characters):
            raise ValueError("캐릭터 수와 목표 횟수의 개수가 일치하지 않아.")
        
        # Calculate individual character probabilities
        individual_probs = []
        for i, (name, rate) in enumerate(characters):
            target = target_counts[i]
            if at_least:
                prob = self._binomial_probability_at_least(attempts, target, rate)
            else:
                prob = self._binomial_probability(attempts, target, rate)
            
            expected = attempts * rate
            individual_probs.append({
                'name': name,
                'rate': rate,
                'rate_percent': rate * 100,
                'target': target,
                'probability': prob,
                'expected': expected
            })
        
        # Calculate scenario probabilities for 2-character case
        if len(characters) == 2:
            scenarios = self._calculate_two_character_scenarios(
                characters, attempts, target_counts, at_least
            )
        else:
            scenarios = self._calculate_multi_character_scenarios(
                characters, attempts, target_counts, at_least
            )
        
        return {
            'characters': individual_probs,
            'scenarios': scenarios,
            'attempts': attempts,
            'at_least': at_least
        }
    
    def _calculate_two_character_scenarios(
        self, 
        characters: List[Tuple[str, float]], 
        attempts: int,
        target_counts: List[int],
        at_least: bool
    ) -> Dict[str, Dict[str, any]]:
        """Calculate the four scenarios for two characters"""
        char_a_name, rate_a = characters[0]
        char_b_name, rate_b = characters[1]
        target_a, target_b = target_counts
        
        # Calculate individual probabilities
        if at_least:
            prob_a_success = self._binomial_probability_at_least(attempts, target_a, rate_a)
            prob_a_zero = self._binomial_probability(attempts, 0, rate_a)
            prob_b_success = self._binomial_probability_at_least(attempts, target_b, rate_b)
            prob_b_zero = self._binomial_probability(attempts, 0, rate_b)
        else:
            prob_a_success = self._binomial_probability(attempts, target_a, rate_a)
            prob_a_zero = self._binomial_probability(attempts, 0, rate_a)
            prob_b_success = self._binomial_probability(attempts, target_b, rate_b)
            prob_b_zero = self._binomial_probability(attempts, 0, rate_b)
        
        # Four scenarios (assuming independence)
        scenarios = {
            'both_success': {
                'description': f'{char_a_name} {target_a}회 이상, {char_b_name} {target_b}회 이상' if at_least else f'{char_a_name} 정확히 {target_a}회, {char_b_name} 정확히 {target_b}회',
                'probability': prob_a_success * prob_b_success,
                'characters': [char_a_name, char_b_name]
            },
            'only_a': {
                'description': f'{char_a_name} {target_a}회 이상, {char_b_name} 0회' if at_least else f'{char_a_name} 정확히 {target_a}회, {char_b_name} 0회',
                'probability': prob_a_success * prob_b_zero,
                'characters': [char_a_name]
            },
            'only_b': {
                'description': f'{char_a_name} 0회, {char_b_name} {target_b}회 이상' if at_least else f'{char_a_name} 0회, {char_b_name} 정확히 {target_b}회',
                'probability': prob_a_zero * prob_b_success,
                'characters': [char_b_name]
            },
            'neither': {
                'description': f'{char_a_name} 0회, {char_b_name} 0회',
                'probability': prob_a_zero * prob_b_zero,
                'characters': []
            }
        }
        
        return scenarios
    
    def _calculate_multi_character_scenarios(
        self, 
        characters: List[Tuple[str, float]], 
        attempts: int,
        target_counts: List[int],
        at_least: bool
    ) -> Dict[str, Dict[str, any]]:
        """Calculate all possible scenarios for multiple characters"""
        scenarios = {}
        num_chars = len(characters)
        
        # Calculate individual character probabilities
        char_success_probs = []
        char_fail_probs = []
        
        for i, (name, rate) in enumerate(characters):
            target = target_counts[i]
            if at_least:
                success_prob = self._binomial_probability_at_least(attempts, target, rate)
            else:
                success_prob = self._binomial_probability(attempts, target, rate)
            
            fail_prob = self._binomial_probability(attempts, 0, rate)
            
            char_success_probs.append(success_prob)
            char_fail_probs.append(fail_prob)
        
        # Generate all possible combinations (2^n scenarios)
        # Each bit represents success (1) or failure (0) for each character
        for combination in range(2**num_chars):
            scenario_prob = 1.0
            successful_chars = []
            description_parts = []
            
            for i in range(num_chars):
                char_name = characters[i][0]
                target = target_counts[i]
                
                # Check if character i succeeds in this combination
                if combination & (1 << i):  # Character succeeds
                    scenario_prob *= char_success_probs[i]
                    successful_chars.append(char_name)
                    if at_least:
                        description_parts.append(f"{char_name} {target}회 이상")
                    else:
                        description_parts.append(f"{char_name} 정확히 {target}회")
                else:  # Character fails
                    scenario_prob *= char_fail_probs[i]
                    description_parts.append(f"{char_name} 0회")
            
            # Create description
            if len(successful_chars) == 0:
                description = "모든 캐릭터 실패"
                scenario_key = "all_fail"
            elif len(successful_chars) == num_chars:
                description = f"모든 캐릭터 성공 ({', '.join(successful_chars)})"
                scenario_key = "all_success"
            else:
                # Create a descriptive key and description
                success_names = ', '.join(successful_chars)
                fail_count = num_chars - len(successful_chars)
                description = f"{success_names} 성공, {fail_count}명 실패"
                scenario_key = f"scenario_{combination}"
            
            scenarios[scenario_key] = {
                'description': description,
                'probability': scenario_prob,
                'characters': successful_chars,
                'combination': combination  # For debugging/sorting
            }
        
        # Sort scenarios by probability (highest first) for better display
        sorted_scenarios = dict(sorted(
            scenarios.items(), 
            key=lambda x: x[1]['probability'], 
            reverse=True
        ))
        
        return sorted_scenarios
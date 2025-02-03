from typing import Dict, Tuple

class ArknightsGachaCalculator:
    """Calculator for Arknights gacha probabilities"""
    
    # Base rates for Arknights
    BASE_6_STAR_RATE = 0.02  # 2%
    PITY_START = 50  # Pity starts increasing after 50 pulls
    PITY_INCREASE_PER_PULL = 0.02  # 2% increase per pull after pity starts
    RATE_UP_CHANCE = 0.5  # Rate up operator has 50% chance when getting 6*
    LIMITED_RATE_UP_CHANCE = 0.35  # Limited operator has 35% chance when getting 6*
    
    # Resource conversion rates
    ORUNDUM_PER_PULL = 600
    ORIGINIUM_TO_ORUNDUM = 180  # 1 Originite Prime = 180 Orundum
    
    @staticmethod
    def calculate_pulls_from_resources(
        orundum: int = 0,
        originite: int = 0,
        permits: int = 0
    ) -> Dict[str, int]:
        """Calculate total possible pulls from resources
        
        Args:
            orundum: Amount of Orundum
            originite: Amount of Originite Prime
            permits: Number of Headhunting Permits
            
        Returns:
            Dict containing:
                'total_pulls': Total number of pulls possible
                'from_orundum': Pulls from Orundum
                'from_originite': Pulls from Originite Prime
                'from_permits': Pulls from permits
        """
        # Calculate pulls from each source
        pulls_from_orundum = orundum // ArknightsGachaCalculator.ORUNDUM_PER_PULL
        orundum_from_originite = originite * ArknightsGachaCalculator.ORIGINIUM_TO_ORUNDUM
        pulls_from_originite = orundum_from_originite // ArknightsGachaCalculator.ORUNDUM_PER_PULL
        
        total_pulls = pulls_from_orundum + pulls_from_originite + permits
        
        return {
            'total_pulls': total_pulls,
            'from_orundum': pulls_from_orundum,
            'from_originite': pulls_from_originite,
            'from_permits': permits
        }
    
    @staticmethod
    def calculate_single_pull_rate(pulls_without_6star: int) -> float:
        """Calculate the rate for a single pull based on pity
        
        Args:
            pulls_without_6star: Number of pulls done without getting a 6 star
            
        Returns:
            float: Probability of getting a 6 star on next pull
        """
        if pulls_without_6star < ArknightsGachaCalculator.PITY_START:
            return ArknightsGachaCalculator.BASE_6_STAR_RATE
            
        increased_rate = ArknightsGachaCalculator.BASE_6_STAR_RATE + \
            (pulls_without_6star - ArknightsGachaCalculator.PITY_START) * \
            ArknightsGachaCalculator.PITY_INCREASE_PER_PULL
        
        return min(increased_rate, 1.0)  # Cap at 100%

    @staticmethod
    def calculate_pull_sequence_probability(start_pity: int, sequence_length: int) -> Tuple[float, float]:
        """Calculate probability of getting 6★ and expected pulls until 6★ from a given pity
        
        Args:
            start_pity: Starting pity count
            sequence_length: Maximum number of pulls to calculate for
            
        Returns:
            Tuple[float, float]: (Probability of getting 6★ within sequence, Expected pulls until 6★)
        """
        prob_no_6star = 1.0
        expected_pulls = 0.0
        cumulative_prob = 0.0
        
        for i in range(sequence_length):
            current_pity = start_pity + i
            rate = ArknightsGachaCalculator.calculate_single_pull_rate(current_pity)
            
            # Probability of reaching this pull (not getting 6★ before)
            prob_reaching_here = prob_no_6star
            
            # Probability of getting 6★ at exactly this pull
            prob_6star_here = prob_reaching_here * rate
            
            # Add to expected value
            expected_pulls += (i + 1) * prob_6star_here
            
            # Update probability of not getting 6★
            prob_no_6star *= (1 - rate)
            
            # Add to cumulative probability
            cumulative_prob += prob_6star_here
            
            # Optimization: break if probability is close to 1
            if cumulative_prob > 0.9999:
                break
        
        return cumulative_prob, expected_pulls

    @staticmethod
    def calculate_banner_probability(pulls: int, is_limited: bool = False) -> Dict[str, float]:
        """Calculate probability of getting desired rate-up operator in X pulls
        
        Args:
            pulls: Number of pulls to calculate for
            is_limited: Whether this is a limited banner (35% rate) or normal banner (50% rate)
            
        Returns:
            Dict with probability info:
                'probability': Chance of getting at least one desired operator
                'expected_6stars': Expected number of 6* operators
                'expected_target': Expected number of target operator
        """
        rate_up_chance = ArknightsGachaCalculator.LIMITED_RATE_UP_CHANCE if is_limited else ArknightsGachaCalculator.RATE_UP_CHANCE
        
        # Initialize counters
        total_prob_no_target = 1.0  # Probability of not getting target operator
        expected_6stars = 0.0
        expected_target = 0.0
        current_pity = 0
        remaining_pulls = pulls
        
        while remaining_pulls > 0:
            # Calculate probabilities for next sequence
            sequence_length = min(remaining_pulls, 99)  # Cap sequence length for efficiency
            prob_6star, exp_pulls = ArknightsGachaCalculator.calculate_pull_sequence_probability(
                current_pity, sequence_length
            )
            
            # Update expected 6★ count
            sequence_expected_6stars = prob_6star
            expected_6stars += sequence_expected_6stars
            
            # Update expected target operator count
            sequence_expected_target = sequence_expected_6stars * rate_up_chance
            expected_target += sequence_expected_target
            
            # Update probability of not getting target
            prob_no_target_this_sequence = (1 - prob_6star) + (prob_6star * (1 - rate_up_chance))
            total_prob_no_target *= prob_no_target_this_sequence
            
            # Update remaining pulls and pity
            pulls_this_sequence = min(int(exp_pulls) if prob_6star > 0.5 else sequence_length, remaining_pulls)
            remaining_pulls -= pulls_this_sequence
            current_pity = 0  # Reset pity after sequence
        
        # Calculate final probability of getting at least one target operator
        probability = 1 - total_prob_no_target
        
        return {
            'probability': probability,
            'expected_6stars': expected_6stars,
            'expected_target': expected_target
        } 
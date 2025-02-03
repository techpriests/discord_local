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
    def calculate_first_6star_distribution(max_pulls: int) -> Tuple[list[float], float]:
        """Calculate probability distribution of getting first 6★
        
        Args:
            max_pulls: Maximum number of pulls to calculate for
            
        Returns:
            Tuple containing:
                - List of probabilities of getting first 6★ at each pull
                - Probability of not getting 6★ within max_pulls
        """
        prob_no_6star = 1.0
        distribution = []
        
        for i in range(max_pulls):
            rate = ArknightsGachaCalculator.calculate_single_pull_rate(i)
            # Probability of getting 6★ exactly at this pull
            prob_6star_here = prob_no_6star * rate
            distribution.append(prob_6star_here)
            # Update probability of not getting 6★
            prob_no_6star *= (1 - rate)
        
        return distribution, prob_no_6star

    @staticmethod
    def calculate_transition_matrix(max_state: int = 99) -> list[list[float]]:
        """Calculate the transition matrix for the Markov chain
        
        Each state represents number of pulls without 6★ (0 to max_state-1)
        Transitions are:
            - Get 6★: Go to state 0
            - No 6★: Go to next state
            
        Args:
            max_state: Maximum number of states (default 99 due to pity)
            
        Returns:
            List of lists representing transition matrix
        """
        matrix = []
        for state in range(max_state):
            row = [0.0] * max_state
            rate = ArknightsGachaCalculator.calculate_single_pull_rate(state)
            # Probability of getting 6★ -> go to state 0
            row[0] = rate
            # Probability of no 6★ -> go to next state
            if state < max_state - 1:
                row[state + 1] = 1 - rate
            else:
                # At max state, guaranteed 6★
                row[0] = 1.0
            matrix.append(row)
        return matrix

    @staticmethod
    def calculate_banner_probability(pulls: int, is_limited: bool = False) -> Dict[str, float]:
        """Calculate probability of getting desired rate-up operator in X pulls
        using Markov chain approach
        
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
        
        # Get transition matrix
        transition = ArknightsGachaCalculator.calculate_transition_matrix()
        
        # Initial state distribution (start at pity 0)
        state = [0.0] * len(transition)
        state[0] = 1.0
        
        # Variables to track
        expected_6stars = 0.0
        prob_no_target = 1.0
        
        # For each pull
        for _ in range(pulls):
            # Calculate probabilities for this pull
            new_state = [0.0] * len(transition)
            for curr_state in range(len(transition)):
                if state[curr_state] > 0.001:  # Optimization: skip negligible states
                    # Get 6★ probability directly from transition matrix
                    prob_6star = state[curr_state] * transition[curr_state][0]
                    expected_6stars += prob_6star
                    # Update probability of not getting target
                    prob_no_target *= (1 - (prob_6star * rate_up_chance))
                    
                    # Update next state
                    for next_state in range(len(transition)):
                        new_state[next_state] += state[curr_state] * transition[curr_state][next_state]
            state = new_state
        
        # Calculate final probabilities
        probability = 1 - prob_no_target
        expected_target = expected_6stars * rate_up_chance
        
        return {
            'probability': probability,
            'expected_6stars': expected_6stars,
            'expected_target': expected_target
        } 
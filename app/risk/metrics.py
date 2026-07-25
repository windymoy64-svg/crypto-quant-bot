from typing import List, Dict
import math

def calculate_correlation_matrix(price_data: Dict[str, List[float]]) -> Dict[str, Dict[str, float]]:
    """Calculate correlation matrix between assets"""
    if len(price_data) < 2:
        return {}
    
    correlation_matrix = {}
    symbols = list(price_data.keys())
    
    for i, symbol1 in enumerate(symbols):
        if symbol1 not in correlation_matrix:
            correlation_matrix[symbol1] = {}
        
        for symbol2 in symbols[i:]:
            if symbol1 not in correlation_matrix:
                correlation_matrix[symbol1] = {}
            if symbol2 not in correlation_matrix:
                correlation_matrix[symbol2] = {}
            
            # Calculate correlation coefficient
            corr = calculate_correlation_coefficient(price_data[symbol1], price_data[symbol2])
            correlation_matrix[symbol1][symbol2] = corr
            correlation_matrix[symbol2][symbol1] = corr
    
    return correlation_matrix

def calculate_correlation_coefficient(prices1: List[float], prices2: List[float]) -> float:
    """Calculate correlation coefficient between two lists of prices"""
    if len(prices1) < 2 or len(prices2) < 2 or len(prices1) != len(prices2):
        return 0.0
    
    # Calculate returns instead of prices
    returns1 = [(prices1[i] - prices1[i-1]) / prices1[i-1] for i in range(1, len(prices1))]
    returns2 = [(prices2[i] - prices2[i-1]) / prices2[i-1] for i in range(1, len(prices2))]
    
    # Calculate means
    mean1 = sum(returns1) / len(returns1)
    mean2 = sum(returns2) / len(returns2)
    
    # Calculate numerator and denominator
    numerator = sum((r1 - mean1) * (r2 - mean2) for r1, r2 in zip(returns1, returns2))
    denominator1 = math.sqrt(sum((r1 - mean1) ** 2 for r1 in returns1))
    denominator2 = math.sqrt(sum((r2 - mean2) ** 2 for r2 in returns2))
    
    if denominator1 == 0 or denominator2 == 0:
        return 0.0
    
    return numerator / (denominator1 * denominator2)
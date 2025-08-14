import time
from collections import defaultdict
from typing import Dict, Any, Optional

import numpy as np


class PerformanceMonitor:
    def __init__(self) -> None:
        self.metrics: Dict[str, Any] = {
            'algorithm_usage': defaultdict(int),
            'balance_scores': defaultdict(list),
            'processing_times': defaultdict(list),
            'user_satisfaction': defaultdict(list),
            'success_rate': defaultdict(list),
        }
        self.start_time = time.time()

    def log_balance_attempt(self, algorithm: str, balance_score: float, processing_time: float, success: bool, user_rating: Optional[float] = None) -> None:
        self.metrics['algorithm_usage'][algorithm] += 1
        self.metrics['balance_scores'][algorithm].append(balance_score)
        self.metrics['processing_times'][algorithm].append(processing_time)
        self.metrics['success_rate'][algorithm].append(1.0 if success else 0.0)
        if user_rating is not None:
            self.metrics['user_satisfaction'][algorithm].append(user_rating)

    def get_performance_summary(self) -> Dict[str, Any]:
        summary = {'uptime_hours': (time.time() - self.start_time) / 3600, 'algorithms': {}}
        for algo in self.metrics['algorithm_usage']:
            usage = self.metrics['algorithm_usage'][algo]
            if usage == 0:
                continue
            scores = self.metrics['balance_scores'][algo]
            times = self.metrics['processing_times'][algo]
            success = self.metrics['success_rate'][algo]
            data = {
                'usage_count': usage,
                'avg_balance_score': float(np.mean(scores)) if scores else 0.0,
                'median_balance_score': float(np.median(scores)) if scores else 0.0,
                'avg_processing_time': float(np.mean(times)) if times else 0.0,
                'success_rate': float(np.mean(success)) if success else 0.0,
                'consistency': float(1.0 - np.std(scores)) if scores else 0.0,
            }
            if self.metrics['user_satisfaction'][algo]:
                data['avg_user_satisfaction'] = float(np.mean(self.metrics['user_satisfaction'][algo]))
            summary['algorithms'][algo] = data
        return summary

    def generate_performance_report(self) -> str:
        s = self.get_performance_summary()
        report = f"# Auto Balance Performance Report\n\n"
        report += f"**System Uptime**: {s['uptime_hours']:.1f} hours\n\n"
        for algo, stats in s['algorithms'].items():
            report += f"## {algo.title()} Algorithm\n"
            report += f"- Usage: {stats['usage_count']} times\n"
            report += f"- Avg Balance Score: {stats['avg_balance_score']:.1%}\n"
            report += f"- Median Balance Score: {stats['median_balance_score']:.1%}\n"
            report += f"- Avg Processing Time: {stats['avg_processing_time']:.2f}s\n"
            report += f"- Success Rate: {stats['success_rate']:.1%}\n"
            report += f"- Consistency: {stats['consistency']:.1%}\n\n"
            if 'avg_user_satisfaction' in stats:
                report += f"- User Satisfaction: {stats['avg_user_satisfaction']:.1f}/5.0\n\n"
        return report


class AlertSystem:
    def __init__(self, performance_monitor: PerformanceMonitor) -> None:
        self.monitor = performance_monitor
        self.alert_thresholds = {
            'min_success_rate': 0.8,
            'max_processing_time': 10.0,
            'min_balance_score': 0.6,
            'min_consistency': 0.7,
        }

    def check_performance_alerts(self) -> list[dict[str, Any]]:
        alerts = []
        summary = self.monitor.get_performance_summary()
        for algo, stats in summary['algorithms'].items():
            if stats['success_rate'] < self.alert_thresholds['min_success_rate']:
                alerts.append({'type': 'low_success_rate', 'algorithm': algo, 'current_value': stats['success_rate'], 'threshold': self.alert_thresholds['min_success_rate'], 'severity': 'high'})
            if stats['avg_processing_time'] > self.alert_thresholds['max_processing_time']:
                alerts.append({'type': 'slow_processing', 'algorithm': algo, 'current_value': stats['avg_processing_time'], 'threshold': self.alert_thresholds['max_processing_time'], 'severity': 'medium'})
            if stats['avg_balance_score'] < self.alert_thresholds['min_balance_score']:
                alerts.append({'type': 'poor_balance_quality', 'algorithm': algo, 'current_value': stats['avg_balance_score'], 'threshold': self.alert_thresholds['min_balance_score'], 'severity': 'medium'})
            if stats['consistency'] < self.alert_thresholds['min_consistency']:
                alerts.append({'type': 'inconsistent_results', 'algorithm': algo, 'current_value': stats['consistency'], 'threshold': self.alert_thresholds['min_consistency'], 'severity': 'low'})
        return alerts



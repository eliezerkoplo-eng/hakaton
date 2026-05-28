from CommentAnalyzer.models.comment import SuspicionLevel
from collections import Counter
from datetime import datetime
import numpy as np
from CommentAnalyzer.models.comment_list import CommentList


class BotNetworkAnalyzer:
    def __init__(self, comment_list: CommentList):
        self.comment_list = comment_list

    def analyze_by_volume(self) -> float:
        if self.comment_list.size() == 0:
            return 0.0
        authors = self.comment_list.get_all_authors()
        total = len(authors)
        counts = Counter(authors)
        _, max_count = counts.most_common(1)[0]
        ratio = max_count / total
        return min(1.0, ratio * 2)

    def analyze_by_text_similarity(self) -> float:
        comments = self.comment_list.get_all_comments()
        total = len(comments)
        if total < 2:
            return 0.0
        texts = [c.cleaned_text for c in comments if c.cleaned_text]
        if len(texts) < 2:
            return 0.0
        if total > 500:
            indices = np.random.choice(total, size=500, replace=False)
            texts = [texts[i] for i in indices]
            total = len(texts)
        duplicates = 0
        pairs_checked = 0
        for i in range(total):
            for j in range(i + 1, total):
                pairs_checked += 1
                set_a = set(texts[i].split())
                set_b = set(texts[j].split())
                union_size = len(set_a.union(set_b))
                if union_size == 0:
                    continue
                jaccard = len(set_a.intersection(set_b)) / union_size
                if jaccard > 0.85:
                    duplicates += 1
        if pairs_checked == 0:
            return 0.0
        return min(1.0, (duplicates / pairs_checked) * 5)

    def analyze_by_time_bursts(self) -> float:
        timestamps = self.comment_list.get_all_timestamps()
        total = len(timestamps)
        if total < 5:
            return 0.0
        ts_array = np.sort(np.array(timestamps))
        max_density = 0
        for ts in ts_array:
            window_count = np.sum((ts_array >= ts) & (ts_array <= ts + 60))
            if window_count > max_density:
                max_density = window_count
        return max_density / total

    def analyze_by_text_patterns(self) -> float:
        comments = self.comment_list.get_all_comments()
        total = len(comments)
        if total == 0:
            return 0.0
        bot_signals = 0
        for c in comments:
            caps_count = sum(1 for char in c.text if char.isupper())
            exclamation_count = c.text.count('!')
            if exclamation_count > 4 or caps_count > 15:
                bot_signals += 1
        return bot_signals / total

    def analyze_by_network_topology(self) -> float:
        comments = self.comment_list.get_all_comments()
        total = len(comments)
        if total < 4:
            return 0.0
        interactions = []
        for c in comments:
            if c.parent_id and c.author:
                interactions.append((c.author, c.parent_id))
        if not interactions:
            return 0.0
        pairs = Counter(interactions)
        if not pairs:
            return 0.0
        _, max_interaction = pairs.most_common(1)[0]
        if max_interaction > 5:
            return min(1.0, max_interaction / 15)
        return 0.0

    def analyze_by_activity_hours(self) -> float:
        timestamps = self.comment_list.get_all_timestamps()
        total = len(timestamps)
        if total < 20:
            return 0.0
        hours = [datetime.utcfromtimestamp(ts).hour for ts in timestamps]
        hour_counts = np.zeros(24)
        for h in hours:
            hour_counts[h] += 1
        active_hours_count = np.sum(hour_counts > 0)
        if active_hours_count < 6:
            return 0.8
        std_dev = np.std(hour_counts)
        mean_val = np.mean(hour_counts)
        if mean_val == 0:
            return 0.0
        cv = std_dev / mean_val
        if cv < 0.2:
            return 0.9
        return 0.0

    def analyze_by_lexical_diversity(self) -> float:
        comments = self.comment_list.get_all_comments()
        if len(comments) < 5:
            return 0.0
        all_words = []
        for c in comments:
            if c.cleaned_text:
                all_words.extend(c.cleaned_text.split())
        total_words = len(all_words)
        if total_words < 50:
            return 0.0
        unique_words = len(set(all_words))
        ttr = unique_words / total_words
        if ttr < 0.15:
            return 1.0
        elif ttr < 0.30:
            return 0.6
        return 0.0

    def analyze(self) -> SuspicionLevel:
        if self.comment_list.size() == 0:
            return SuspicionLevel.VERY_LOW
        v1 = self.analyze_by_volume()
        v2 = self.analyze_by_text_similarity()
        v3 = self.analyze_by_time_bursts()
        v4 = self.analyze_by_text_patterns()
        v5 = self.analyze_by_network_topology()
        v6 = self.analyze_by_activity_hours()
        v7 = self.analyze_by_lexical_diversity()
        final_score = (
                (v1 * 0.20) +
                (v2 * 0.20) +
                (v3 * 0.15) +
                (v4 * 0.10) +
                (v5 * 0.10) +
                (v6 * 0.10) +
                (v7 * 0.15)
        )
        if final_score <= 0.15:
            return SuspicionLevel.VERY_LOW
        elif final_score <= 0.35:
            return SuspicionLevel.LOW
        elif final_score <= 0.60:
            return SuspicionLevel.MEDIUM
        elif final_score <= 0.80:
            return SuspicionLevel.HIGH
        else:
            return SuspicionLevel.VERY_HIGH

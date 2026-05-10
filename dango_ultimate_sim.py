# -*- coding: utf-8 -*-
import argparse
import csv
import gc
import statistics
import time
import random
from collections import Counter
from dataclasses import dataclass

# ==========================================
# 赛道与装置全局配置
# ==========================================
TRACK_LENGTH = 32
BO_DA_WANG_START = 32
BO_DA_WANG_TURN = 3

BOOST_TILES = {3, 11, 16, 23}   
BLOCK_TILES = {10, 28}          
RIFT_TILES = {6, 20}            

NORMAL_NAMES = ["千咲", "莫宁", "琳奈", "爱弥斯", "守岸人", "珂莱塔"]

# ==========================================
# 游戏内核模块
# ==========================================
class Tuanzi:
    def __init__(self, name, skill_type):
        self.name = name
        self.skill_type = skill_type
        self.reset()

    def reset(self):
        self.pos = 1
        self.stack_order = 1
        self.finished = False
        self.morning_cycle = [3, 2, 1]
        self.morning_idx = 0
        self.amis_used = False

    def roll(self, rng):
        # 布大王：1-6
        if self.name == "布大王":
            return rng.randint(1, 6)

        # 莫宁：3-2-1 循环
        if self.skill_type == "Morning":
            val = self.morning_cycle[self.morning_idx % 3]
            self.morning_idx += 1
            return val
            
        # 守岸人：固定 2 或 3
        if self.skill_type == "Shorekeeper":
            return rng.choice([2, 3])
        
        # 普通角色基础：1-3
        base_roll = rng.randint(1, 3)
        
        # 琳奈：20% 宕机(0)，60% 双倍，20% 正常
        if self.skill_type == "Linne":
            p = rng.random()
            if p < 0.20: return 0
            elif p < 0.80: return base_roll * 2
            else: return base_roll
        
        # 珂莱塔：28% 双倍
        if self.skill_type == "Colette":
            if rng.random() < 0.28: return base_roll * 2
            return base_roll
            
        return base_roll

class GameEngine:
    def __init__(self, rng):
        self.rng = rng
        self.dangos = [
            Tuanzi("千咲", "Chisaki"), Tuanzi("莫宁", "Morning"),
            Tuanzi("琳奈", "Linne"), Tuanzi("爱弥斯", "Amis"),
            Tuanzi("守岸人", "Shorekeeper"), Tuanzi("珂莱塔", "Colette")
        ]
        self.bdw = Tuanzi("布大王", "BDW")
        self.bdw.pos = BO_DA_WANG_START
        self.winners = []
        self.turn = 0

    def refresh_stacks(self, last_moved_names):
        all_active = [d for d in self.dangos if not d.finished]
        if self.turn >= BO_DA_WANG_TURN:
            all_active.append(self.bdw)
            
        tiles = set(d.pos for d in all_active)
        for t in tiles:
            on_tile = [d for d in all_active if d.pos == t]
            if t == 1 or len(on_tile) <= 1:
                for d in on_tile: d.stack_order = 1
                continue
            
            bdws = [d for d in on_tile if d.name == "布大王"]
            others = [d for d in on_tile if d.name != "布大王"]
            others.sort(key=lambda x: x.name in last_moved_names, reverse=True)
            
            new_stack = others + bdws
            for i, d in enumerate(new_stack):
                d.stack_order = i + 1

    def run_game(self) -> tuple[list[str], int]:
        while len(self.winners) < 6:
            self.turn += 1
            active_list = [d for d in self.dangos if not d.finished]
            if not active_list: break
            
            order = active_list + ([self.bdw] if self.turn >= BO_DA_WANG_TURN else [])
            self.rng.shuffle(order)
            
            round_rolls = {d.name: d.roll(self.rng) for d in order}
            min_roll_val = min(round_rolls.values())

            moved_this_turn = set()
            for actor in order:
                if actor.name in moved_this_turn or (actor.name != "布大王" and actor.finished):
                    continue
                
                steps = round_rolls[actor.name]
                if actor.name == "千咲" and steps == min_roll_val:
                    steps += 2
                
                group = [actor]
                if actor.name != "布大王" and actor.pos > 1:
                    group = [o for o in active_list if o.pos == actor.pos and o.stack_order <= actor.stack_order]
                
                for m in group:
                    m.pos += (-steps if m.name == "布大王" else steps)
                    
                    if m.skill_type == "Amis" and not m.amis_used and m.pos > 16:
                        ahead = [o for o in active_list if o.pos > m.pos and o.name != "布大王"]
                        if ahead:
                            m.pos = min(ahead, key=lambda x: x.pos).pos
                            m.amis_used = True

                    while True:
                        prev_pos = m.pos
                        if m.pos in BOOST_TILES: m.pos += 1
                        elif m.pos in BLOCK_TILES: m.pos -= 1
                        if m.pos == prev_pos: break
                    
                    if m.name != "布大王" and m.pos >= 32:
                        m.finished = True
                    moved_this_turn.add(m.name)
                
                for m in group:
                    if m.pos in RIFT_TILES:
                        on_rift = [o for o in (active_list + ([self.bdw] if self.turn >= BO_DA_WANG_TURN else [])) if o.pos == m.pos]
                        self.rng.shuffle(on_rift) 
                
                self.refresh_stacks(moved_this_turn)

            round_winners = sorted([d for d in active_list if d.finished and d not in self.winners], key=lambda x: x.stack_order)
            self.winners.extend(round_winners)

            if self.turn >= BO_DA_WANG_TURN:
                if not any(o.pos == self.bdw.pos for o in active_list):
                    self.bdw.pos = BO_DA_WANG_START

        return [w.name for w in self.winners], self.turn

# ==========================================
# 统计与输出分析模块 (基于用户提供的逻辑)
# ==========================================
def mean_or_zero(values: list[float]) -> float:
    return statistics.mean(values) if values else 0.0

def stdev_or_zero(values: list[float]) -> float:
    return statistics.stdev(values) if len(values) >= 2 else 0.0

def expected_rank_from_rank_count(rank_count: dict[str, Counter], n: int) -> dict[str, float]:
    expected_rank = {}
    for name in NORMAL_NAMES:
        exp = 0.0
        for rank_index in range(1, 7):
            prob = rank_count[name][rank_index] / n
            exp += rank_index * prob
        expected_rank[name] = exp
    return expected_rank

def predicted_order_from_expected_rank(expected_rank: dict[str, float]) -> list[str]:
    return sorted(NORMAL_NAMES, key=lambda name: expected_rank[name])

def print_order(order: list[str]) -> str:
    return " > ".join(order)

def run_one_seed(n: int, seed: int) -> dict:
    rng = random.Random(seed)

    champion_count = Counter()
    advance_count = Counter()
    round_count = Counter()
    rank_count: dict[str, Counter] = {name: Counter() for name in NORMAL_NAMES}

    for _ in range(n):
        engine = GameEngine(rng)
        winners, round_no = engine.run_game()

        champion_count[winners[0]] += 1
        for rank_index, name in enumerate(winners, start=1):
            if rank_index <= 4:
                advance_count[name] += 1
            rank_count[name][rank_index] += 1
        
        round_count[round_no] += 1

    expected_rank = expected_rank_from_rank_count(rank_count, n)
    predicted_order = predicted_order_from_expected_rank(expected_rank)
    avg_round = sum(k * v for k, v in round_count.items()) / n

    champion_rate = {name: champion_count[name] / n * 100 for name in NORMAL_NAMES}
    advance_rate = {name: advance_count[name] / n * 100 for name in NORMAL_NAMES}
    rank_rate = {
        name: {rank_index: rank_count[name][rank_index] / n * 100 for rank_index in range(1, 7)}
        for name in NORMAL_NAMES
    }

    return {
        "seed": seed, "n": n, "champion_count": champion_count, "advance_count": advance_count,
        "rank_count": rank_count, "round_count": round_count, "champion_rate": champion_rate,
        "advance_rate": advance_rate, "rank_rate": rank_rate, "expected_rank": expected_rank,
        "predicted_order": predicted_order, "avg_round": avg_round,
    }

def run_multi_seed(n_per_seed: int, base_seed: int, num_seeds: int, pause_seconds: float, csv_path: str) -> None:
    seeds = [base_seed + i for i in range(num_seeds)]

    all_champion_count = Counter()
    all_advance_count = Counter()
    all_rank_count: dict[str, Counter] = {name: Counter() for name in NORMAL_NAMES}
    all_round_count = Counter()

    champion_rate_series = {name: [] for name in NORMAL_NAMES}
    advance_rate_series = {name: [] for name in NORMAL_NAMES}
    expected_rank_series = {name: [] for name in NORMAL_NAMES}
    rank_rate_series = {name: {r: [] for r in range(1, 7)} for name in NORMAL_NAMES}
    avg_round_series = []

    print("=== 多 seed 稳定性检验开始 ===")
    print(f"每个 seed 模拟次数：{n_per_seed}")
    print(f"seed 数量：{num_seeds}")
    print(f"总模拟次数：{n_per_seed * num_seeds}")
    print("执行方式：单线程顺序运行，不开多进程。")
    print(f"每个 seed 之间暂停：{pause_seconds} 秒\n")

    with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow([
            "seed", "n", "predicted_order", "avg_round",
            *[f"{name}_expected_rank" for name in NORMAL_NAMES],
            *[f"{name}_champion_rate" for name in NORMAL_NAMES],
            *[f"{name}_advance_rate" for name in NORMAL_NAMES],
            *[f"{name}_rank_{rank_index}_rate" for name in NORMAL_NAMES for rank_index in range(1, 7)],
        ])

        for index, seed in enumerate(seeds, start=1):
            start_time = time.time()
            result = run_one_seed(n=n_per_seed, seed=seed)

            all_champion_count.update(result["champion_count"])
            all_advance_count.update(result["advance_count"])
            all_round_count.update(result["round_count"])

            for name in NORMAL_NAMES:
                all_rank_count[name].update(result["rank_count"][name])
                champion_rate_series[name].append(result["champion_rate"][name])
                advance_rate_series[name].append(result["advance_rate"][name])
                expected_rank_series[name].append(result["expected_rank"][name])
                for rank_index in range(1, 7):
                    rank_rate_series[name][rank_index].append(result["rank_rate"][name][rank_index])

            avg_round_series.append(result["avg_round"])
            elapsed = time.time() - start_time

            print(f"[{index}/{num_seeds}] seed={seed} 完成 | 平均回合={result['avg_round']:.2f} | 耗时={elapsed:.1f}s")
            print(f"预测排序：{print_order(result['predicted_order'])}\n")

            writer.writerow([
                seed, n_per_seed, print_order(result["predicted_order"]), f"{result['avg_round']:.6f}",
                *[f"{result['expected_rank'][name]:.6f}" for name in NORMAL_NAMES],
                *[f"{result['champion_rate'][name]:.6f}" for name in NORMAL_NAMES],
                *[f"{result['advance_rate'][name]:.6f}" for name in NORMAL_NAMES],
                *[f"{result['rank_rate'][name][r]:.6f}" for name in NORMAL_NAMES for r in range(1, 7)],
            ])
            f.flush()

            del result
            gc.collect()

            if pause_seconds > 0 and index < num_seeds:
                time.sleep(pause_seconds)

    total_n = n_per_seed * num_seeds

    print("=== 多 seed 稳定性汇总：夺冠率 ===")
    print(f"{'角色':<6}{'均值':>10}{'标准差':>10}{'最小值':>10}{'最大值':>10}")
    for name in NORMAL_NAMES:
        values = champion_rate_series[name]
        print(f"{name:<6}{mean_or_zero(values):>9.2f}%{stdev_or_zero(values):>9.2f}%{min(values):>9.2f}%{max(values):>9.2f}%")

    print("\n=== 多 seed 稳定性汇总：晋级率 ===")
    print(f"{'角色':<6}{'均值':>10}{'标准差':>10}{'最小值':>10}{'最大值':>10}")
    for name in NORMAL_NAMES:
        values = advance_rate_series[name]
        print(f"{name:<6}{mean_or_zero(values):>9.2f}%{stdev_or_zero(values):>9.2f}%{min(values):>9.2f}%{max(values):>9.2f}%")

    print("\n=== 多 seed 稳定性汇总：期望名次 ===")
    print(f"{'角色':<6}{'均值':>10}{'标准差':>10}{'最小值':>10}{'最大值':>10}")
    for name in NORMAL_NAMES:
        values = expected_rank_series[name]
        print(f"{name:<6}{mean_or_zero(values):>10.4f}{stdev_or_zero(values):>10.4f}{min(values):>10.4f}{max(values):>10.4f}")

    print("\n=== 多 seed 稳定性汇总：第1~6名概率均值 ± 标准差 ===")
    header = f"{'角色':<6}" + "".join([f"{i}名".rjust(18) for i in range(1, 7)])
    print(header)
    print("-" * len(header))
    for name in NORMAL_NAMES:
        row = f"{name:<6}"
        for rank_index in range(1, 7):
            values = rank_rate_series[name][rank_index]
            row += f"{mean_or_zero(values):7.2f}±{stdev_or_zero(values):5.2f}%"
        print(row)

    print("\n=== 平均结束回合稳定性 ===")
    print(f"均值：{mean_or_zero(avg_round_series):.4f}")
    print(f"标准差：{stdev_or_zero(avg_round_series):.4f}")
    print(f"最小值：{min(avg_round_series):.4f}")
    print(f"最大值：{max(avg_round_series):.4f}")

    print("\n=== 全部 seed 合并后的夺冠率 ===")
    for name in NORMAL_NAMES:
        rate = all_champion_count[name] / total_n * 100
        print(f"{name:<5} {rate:6.2f}%")

    print("\n=== 全部 seed 合并后的晋级率：前4名 ===")
    for name in NORMAL_NAMES:
        rate = all_advance_count[name] / total_n * 100
        print(f"{name:<5} {rate:6.2f}%")

    print("\n=== 全部 seed 合并后的第1~6名概率 ===")
    header = f"{'角色':<6}" + "".join([f"{i}名".rjust(10) for i in range(1, 7)])
    print(header)
    print("-" * len(header))
    for name in NORMAL_NAMES:
        row = f"{name:<6}"
        for rank_index in range(1, 7):
            rate = all_rank_count[name][rank_index] / total_n * 100
            row += f"{rate:9.2f}%"
        print(row)

    print()
    combined_expected_rank = expected_rank_from_rank_count(all_rank_count, total_n)
    combined_predicted_order = predicted_order_from_expected_rank(combined_expected_rank)

    print("=== 全部 seed 合并后的预测排序 ===")
    for idx, name in enumerate(combined_predicted_order, start=1):
        print(f"{idx}. {name}，期望名次：{combined_expected_rank[name]:.4f}")

    print(f"\n每个 seed 的详细结果已写入：{csv_path}")

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--n", type=int, default=10000, help="每个 seed 的模拟次数")
    parser.add_argument("--base-seed", type=int, default=20260509, help="起始随机种子")
    parser.add_argument("--num-seeds", type=int, default=10, help="seed 数量，建议 10~30")
    parser.add_argument("--pause", type=float, default=0.5, help="每个 seed 之间暂停秒数")
    parser.add_argument("--csv", type=str, default="tuanzi_stability_results.csv", help="CSV 输出文件名")
    
    args = parser.parse_args()

    run_multi_seed(
        n_per_seed=args.n,
        base_seed=args.base_seed,
        num_seeds=args.num_seeds,
        pause_seconds=args.pause,
        csv_path=args.csv,
    )

if __name__ == "__main__":
    main()
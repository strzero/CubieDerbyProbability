import random
from collections import defaultdict

class Dango:
    def __init__(self, name):
        self.name = name
        self.pos = 1  
        self.last_roll = 0
        self.met_bu = False
        self.caticia_buff = False
        self.sigrika_debuff = 0 

class LudoGame:
    def __init__(self, player_names):
        self.players = [Dango(name) for name in player_names]
        self.bu_dawang_pos = 32 
        self.bu_active = False
        self.round_num = 0
        self.stacks = defaultdict(list)
        
        initial_order = self.players.copy()
        random.shuffle(initial_order)
        for p in initial_order:
            self.stacks[1].append(p)
            
        self.caticia_triggered = False 
        
    def get_rankings(self):
        active_players = [p for p in self.players if p.pos < 32]
        active_players.sort(key=lambda p: (p.pos, self.stacks[p.pos].index(p)), reverse=True)
        return active_players

    def move_dango(self, dango, steps):
        if dango.pos >= 32: return None
        
        current_pos = dango.pos
        
        if current_pos == 1:
            self.stacks[1].remove(dango)
            moving_group = [dango]
        else:
            stack_idx = self.stacks[current_pos].index(dango)
            moving_group = self.stacks[current_pos][stack_idx:]
            self.stacks[current_pos] = self.stacks[current_pos][:stack_idx]
        
        new_pos = min(32, max(1, current_pos + steps)) 
        
        for p in moving_group:
            old_p_pos = p.pos
            p.pos = new_pos
            if self.bu_active and p.name == "绯雪" and not p.met_bu:
                if min(old_p_pos, new_pos) <= self.bu_dawang_pos <= max(old_p_pos, new_pos):
                    p.met_bu = True
                    
        self.stacks[new_pos].extend(moving_group)
        return new_pos

    def apply_track_mechanics(self, pos, dango):
        if pos == 3: self.trigger_device(dango, 1, is_forward=True)
        elif pos == 6: random.shuffle(self.stacks[pos])
        elif pos == 10: self.trigger_device(dango, -1, is_forward=False)
        elif pos == 11: self.trigger_device(dango, 1, is_forward=True)
        elif pos == 16: self.trigger_device(dango, 1, is_forward=True)
        elif pos == 20: random.shuffle(self.stacks[pos])
        elif pos == 23: self.trigger_device(dango, 1, is_forward=True)
        elif pos == 28: self.trigger_device(dango, -1, is_forward=False)

    def trigger_device(self, triggering_dango, base_steps, is_forward):
        extra = 0
        if triggering_dango.name == "陆·赫斯":
            if is_forward: extra = 3
            else: extra = -1
        self.move_dango(triggering_dango, base_steps + extra)

    def move_bu(self, steps):
        old_bu = self.bu_dawang_pos
        self.bu_dawang_pos += steps
        for p in self.players:
            if p.name == "绯雪" and not p.met_bu:
                if min(old_bu, self.bu_dawang_pos) <= p.pos <= max(old_bu, self.bu_dawang_pos):
                    p.met_bu = True

    def play(self):
        while True:
            self.round_num += 1
            action_order = self.players.copy()
            random.shuffle(action_order) 
            
            for current_dango in action_order:
                if current_dango.pos >= 32: continue
                
                roll = random.randint(1, 3)
                
                if current_dango.name == "西格莉卡":
                    rankings = self.get_rankings()
                    try:
                        my_idx = rankings.index(current_dango)
                        targets = rankings[max(0, my_idx-2) : my_idx]
                        for t in targets:
                            t.sigrika_debuff += 1
                    except ValueError: pass
                
                steps = roll
                
                if current_dango.sigrika_debuff > 0:
                    steps -= 1
                    current_dango.sigrika_debuff -= 1
                    if steps < 1: steps = 1
                
                if current_dango.name == "达妮娅" and current_dango.last_roll == roll and self.round_num > 1:
                    steps += 2
                current_dango.last_roll = roll
                
                if current_dango.name == "绯雪" and current_dango.met_bu:
                    steps += 1
                    
                if current_dango.name == "卡提希娅" and current_dango.caticia_buff:
                    if random.random() < 0.6: steps += 2
                        
                if current_dango.name == "菲比":
                    if random.random() < 0.5: steps += 1

                new_pos = self.move_dango(current_dango, steps)
                
                if new_pos is not None:
                    self.apply_track_mechanics(new_pos, current_dango)
                
                if current_dango.name == "卡提希娅" and not self.caticia_triggered:
                    rankings = self.get_rankings()
                    if rankings and rankings[-1] == current_dango:
                        current_dango.caticia_buff = True
                        self.caticia_triggered = True

                if any(p.pos >= 32 for p in self.players):
                    return self.finalize_game()

            if self.round_num == 3:
                self.bu_active = True
                
            if self.bu_active:
                bu_roll = random.randint(1, 6)
                self.move_bu(-bu_roll) 
                
                if self.bu_dawang_pos in [3, 11, 16, 23]: 
                    self.move_bu(1)
                elif self.bu_dawang_pos in [10, 28]: 
                    self.move_bu(-1)
                
                rankings = self.get_rankings()
                if rankings and self.bu_dawang_pos < rankings[-1].pos:
                    self.bu_dawang_pos = 32

    def finalize_game(self):
        final_rank = sorted(self.players, key=lambda p: (p.pos, self.stacks[p.pos].index(p) if p in self.stacks[p.pos] else -1), reverse=True)
        return [p.name for p in final_rank]


# ---------------- 运行测试 ----------------
SIMULATION_TIMES = 100000

player_names = ["陆·赫斯", "西格莉卡", "达妮娅", "绯雪", "卡提希娅", "菲比"]

results = {name: {"wins": 0, "top4": 0} for name in player_names}

for _ in range(SIMULATION_TIMES):
    game = LudoGame(player_names)
    ranking = game.play()
    
    results[ranking[0]]["wins"] += 1
    for name in ranking[:min(4, len(player_names))]:
        results[name]["top4"] += 1

print(f"【 模拟 {SIMULATION_TIMES} 场比赛最终结果 】")
print("=" * 45)

sorted_results = sorted(results.items(), key=lambda x: x[1]['wins'], reverse=True)

for i, (name, data) in enumerate(sorted_results, 1):
    win_rate = (data['wins'] / SIMULATION_TIMES) * 100
    top4_rate = (data['top4'] / SIMULATION_TIMES) * 100
    
    # 采用列表卡片式输出，避免任何由于中英文字符宽度不同导致的排版错位
    print(f"第 {i} 名：[{name}]")
    print(f"冠军次数: {data['wins']}  (胜率: {win_rate:.2f}%)")
    print(f"前四次数: {data['top4']}  (前四率: {top4_rate:.2f}%)")
    print("-" * 45)
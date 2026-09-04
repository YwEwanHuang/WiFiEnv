# WiFiEnv — 科研级 Wi-Fi 仿真环境

面向 **信道选择、发射功率控制、CCA 调优、多 BSS、MLO（STR）** 算法的离散事件仿真环境。无需 ns-3，即可在 Python 中快速迭代。

> 不是 ns-3 克隆，不是完整 IEEE 802.11 协议栈。**Core v1.0 已冻结**，基准数据见 `V1_RELEASE_REPORT.md`。

---

## 当前能力（v1.0）

- 离散事件时序（纳秒级 / 9 µs slot）
- CSMA/CA： DIFS / 退避 / 冻结恢复 / TX / ACK / 重传
- 碰撞、ACK 失败、重传、超过 `retry_limit` 后丢弃
- 包级 PHY（线性域 SINR + 每链路阴影衰落缓存）
- 理想 MCS 选速 + 简化 PER + 包空口时间估算
- 每 (AP, link) FIFO 队列
- 真实干扰流量（干扰 AP 同样运行 CSMA/CA，非始终发送）
- 多 BSS，多信道（≥ 4 AP，≥ 3 信道）
- 每链路 Controller（`link_id` 粒度的信道 / 功率 / CCA）
- `ScriptedRunner` 固定参数驱动（无需 RL）
- 指标：吞吐量、延迟（均值/p50/p95）、队列长度、碰撞、重传、丢弃、**每信道利用率**、每链路分解
- 确定性可复现（相同 scenario + seed + config → 逐比特一致）
- **MLO v0 Feature Pack**：双链路 MLD、各链路独立 CSMA/CA、固定/轮询 steering、STR 模式

### 已明确排除（留待 Feature Pack）

| 功能 | 原因 |
|---|---|
| IEEE 802.11be NSTR / EMLSR | 未来 MLO 论文 |
| OFDMA / MU-MIMO / 320 MHz | OFDMA 论文 |
| BSS Coloring / OBSS_PD / Spatial Reuse | SR 论文 |
| EDCA / QoS AC / Block ACK / A-MPDU | QoS 论文 |
| Capture effect / 空间相关阴影 | Capture 论文 |
| 移动性 / TCP / IP 协议栈 | 移动性论文 |

---

## 快速开始

```bash
# Core 场景（v1.0）
python -m wifi_simulator.scenarios.scenario_a          # 1 AP，饱和流量
python -m wifi_simulator.scenarios.scenario_b          # 2 AP，同信道，饱和流量
python -m wifi_simulator.scenarios.scenario_c          # 4 AP，3 信道，多 BSS

# MLO v0 Feature Pack
python -m wifi_simulator.scenarios.m1_two_link_str     # 1 MLD，2 链路，STR

# 回归测试
python -m wifi_simulator.tests.test_primitives         # 11 项基础检查
python -m wifi_simulator.tests.test_freeze_resume      # 5 项 CSMA/CCA 检查
python -m wifi_simulator.tests.test_sprint1            # A + B 端到端集成
python -m wifi_simulator.experiments.mlo_v0_validation # MLO v0 + 包守恒验证
```

所有命令无需 RL，直接输出 JSON 结果摘要。

---

## 最简示例

```python
from wifi_simulator.core.simulator import ApStation, Simulator

sim = Simulator(
    seed=2024,                       # 确定性
    duration_s=5.0,                  # 仿真时长（秒）
    aps=[
        ApStation(
            ap_id=0, sta_id=10,
            pos_ap=(0.0, 0.0),        # AP 坐标 (x, y) 米
            pos_sta=(10.0, 0.0),      # STA 坐标 (x, y) 米
            link_id=0, channel_id=0,  # 单链路，在信道 0
            tx_power_dbm=18.0,        # 发射功率 dBm
            lambda_pps=100000.0,      # 泊松到达率（包/秒）
            size_bytes=2304,          # 每包载荷大小
        ),
    ],
)
result = sim.run()

print(f"吞吐量   = {result['total_throughput_bps']/1e6:.2f} Mbps")
print(f"成功     = {result['total_success_packets']}")
print(f"丢弃     = {result['total_drop_packets']}")
print(f"延迟 p95 = {result['latency_p95_us']:.1f} µs")
print(f"利用率   = {result['channel_utilization']}")
print(f"每链路   = {result['per_link']}")
```

`result` 字典包含以下字段：

| 字段 | 单位 | 含义 |
|---|---|---|
| `total_throughput_bps` | bits/s | 成功传输的载荷比特/仿真时长（**goodput**） |
| `total_success_packets` | count | 成功交付的包数 |
| `total_drop_packets` | count | 超过 `retry_limit` 后丢弃的包数 |
| `latency_mean_us` | µs | 入队→成功平均延迟 |
| `latency_p50_us` | µs | 中位延迟 |
| `latency_p95_us` | µs | 95 分位延迟 |
| `per_link` | dict | 按 `link_id` 分链路统计 |
| `channel_utilization` | dict | 按 `channel_id` 的信道忙闲比例 `[0, 1]` |

---

## 可复现性

> 相同 scenario + 相同 seed + 相同 config → **逐比特一致**（包括每信道利用率和延迟分位）

唯一随机源是 `Simulator` 内置的单一 `numpy.random.Generator`，所有随机过程（退避计数、阴影、泊松到达）均经此生成。

v1 基准数据：

| 场景 | Seed | 吞吐量 |
|---|---:|---:|
| A | 2024 | 64.83 Mbps |
| B | 2024 | 70.94 Mbps |
| C | 6 | 207.84 Mbps |
| M1 STR | 2024 | 129.75 Mbps |

---

## 相关文档

| 文件 | 内容 |
|---|---|
| `docs/USAGE_GUIDE.md` | **推荐入门文档**：库使用思路、场景运行方式、实验构建方法、参数说明、扩展规范 |
| `V1_RELEASE_REPORT.md` | 基准数据（seed，5 s）、冻结 checklist、已知简化项、运行耗时 |
| `ENV_MVP_REPORT.md` | 环境 MVP 设计与验收记录 |
| `MLO_V0_REPORT.md` | MLO v0 Feature Pack 实现记录与验证结果 |
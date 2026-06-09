import pandas as pd
import matplotlib.pyplot as plt

# 1. 你的数据
data = {
    "产线":["A线","B线","C线","D线","E线"],
    "人数":[25,32,18,40,22],
    "生产总数":[12500,14800,9600,16200,11300]
}
df = pd.DataFrame(data)

# 2. 双轴组合图：左轴产量(柱状)，右轴人数(折线)
fig, ax1 = plt.subplots(figsize=(10,6))

# 产量柱状图
ax1.bar(df["产线"], df["生产总数"], color="#3498db", label="生产总数")
ax1.set_ylabel("生产总数", fontsize=12)
ax1.set_xlabel("产线", fontsize=12)

# 人数折线图（双Y轴）
ax2 = ax1.twinx()
ax2.plot(df["产线"], df["人数"], color="#e74c3c", marker="o", linewidth=2, label="人数")
ax2.set_ylabel("人数", fontsize=12)

# 图例、标题
fig.legend(loc="upper right", bbox_to_anchor=(0.9,0.9))
plt.title("各产线人数与生产总数对比", fontsize=14)
plt.tight_layout()
plt.show()
import type { Locale } from "./locale";

type TranslationMap = Partial<Record<Locale, string>>;

const phrases: Record<string, TranslationMap> = {
  "Account access": { ru: "Доступ к аккаунту", zh: "账户访问" },
  "Account drawdown": { ru: "Просадка аккаунта", zh: "账户回撤" },
  "Active": { ru: "Активные", zh: "活跃" },
  "Active Signals": { ru: "Активные сигналы", zh: "活跃信号" },
  "Add": { ru: "Добавить", zh: "添加" },
  "Adjusted risk": { ru: "Скорректированный риск", zh: "调整后风险" },
  "Advanced": { ru: "Расширенный", zh: "高级" },
  "Aggressive": { ru: "Агрессивный", zh: "激进" },
  "All pairs": { ru: "Все пары", zh: "全部交易对" },
  "All pairs - quality filter on": { ru: "Все пары, фильтр качества включен", zh: "全部交易对，质量过滤已开启" },
  "All seeded pairs added": { ru: "Все загруженные пары добавлены", zh: "已添加全部预置交易对" },
  "Allowed": { ru: "Разрешён", zh: "允许" },
  "Analytics": { ru: "Аналитика", zh: "分析" },
  "API key": { ru: "API-ключ", zh: "API 密钥" },
  "API passphrase": { ru: "API passphrase", zh: "API 口令" },
  "API secret": { ru: "API-секрет", zh: "API 私钥" },
  "Auto Entry": { ru: "Автовход", zh: "自动入场" },
  "Auto Paper": { ru: "Авто Paper", zh: "自动 Paper" },
  "Auto Paper Armed": { ru: "Auto Paper взведён", zh: "自动 Paper 已布置" },
  "Auto reduce after losses": { ru: "Снижать риск после убытков", zh: "亏损后自动降低风险" },
  "Automatic quality filter excludes bad instruments before strategy setup.": {
    ru: "Автоматический фильтр качества исключает слабые инструменты до проверки стратегии.",
    zh: "自动质量过滤会在策略 setup 前排除较差标的。"
  },
  "Balance": { ru: "Баланс", zh: "余额" },
  "Balanced": { ru: "Сбалансированный", zh: "均衡" },
  "Balanced is the default profile. Limits reduce risk exposure but cannot guarantee safety.": {
    ru: "Сбалансированный профиль используется по умолчанию. Лимиты снижают риск, но не гарантируют безопасность.",
    zh: "均衡是默认配置。限制会降低风险敞口，但不能保证安全。"
  },
  "BB squeeze %": { ru: "BB squeeze %", zh: "布林收缩 %" },
  "Bid / Ask": { ru: "Bid / Ask", zh: "买一 / 卖一" },
  "Billing": { ru: "Биллинг", zh: "账单" },
  "Book depth": { ru: "Глубина стакана", zh: "盘口深度" },
  "Breakout Entries": { ru: "Входы на breakout", zh: "突破入场" },
  "Breakeven": { ru: "Безубыток", zh: "保本" },
  "Browser": { ru: "Браузер", zh: "浏览器" },
  "Candles": { ru: "Свечи", zh: "K线" },
  "Candle history is still warming up": { ru: "История свечей ещё прогревается", zh: "K线历史仍在预热" },
  "candles analyzed": { ru: "свечей проанализировано", zh: "已分析K线" },
  "Chart": { ru: "График", zh: "图表" },
  "Checking": { ru: "Проверка", zh: "检查中" },
  "Checking session": { ru: "Проверяем сессию", zh: "正在检查会话" },
  "Checkout": { ru: "Оплатить", zh: "结账" },
  "Close": { ru: "Закрыть", zh: "关闭" },
  "Close market": { ru: "Закрыть по рынку", zh: "市价关闭" },
  "Close-only": { ru: "Только закрытие", zh: "仅平仓" },
  "Confidence": { ru: "Уверенность", zh: "置信度" },
  "Confidence Score": { ru: "Оценка уверенности", zh: "置信评分" },
  "Confirm volume x": { ru: "Объём подтверждения x", zh: "确认成交量 x" },
  "Connect": { ru: "Подключить", zh: "连接" },
  "Connection issue": { ru: "Проблема соединения", zh: "连接问题" },
  "Connection label": { ru: "Название подключения", zh: "连接名称" },
  "Conservative": { ru: "Консервативный", zh: "保守" },
  "Context TF": { ru: "Контекст TF", zh: "上下文周期" },
  "Correlated": { ru: "Корреляция", zh: "相关性" },
  "Correlated risk": { ru: "Коррелированный риск", zh: "相关风险" },
  "Current": { ru: "Текущая", zh: "当前" },
  "Custom": { ru: "Свои", zh: "自定义" },
  "Daily": { ru: "День", zh: "日" },
  "Daily risk": { ru: "Дневной риск", zh: "日风险" },
  "Daily Stop-Loss": { ru: "Дневной Stop-Loss", zh: "日止损" },
  "Data may be delayed": { ru: "Данные могут запаздывать", zh: "数据可能延迟" },
  "Decay 60s": { ru: "Затухание 60с", zh: "60秒衰减" },
  "Default": { ru: "По умолчанию", zh: "默认" },
  "Default profile": { ru: "Профиль по умолчанию", zh: "默认配置" },
  "Depth, spread, slippage": { ru: "Глубина, spread, slippage", zh: "深度、价差、滑点" },
  "Delete": { ru: "Удалить", zh: "删除" },
  "Direction": { ru: "Направление", zh: "方向" },
  "Drawdown": { ru: "Просадка", zh: "回撤" },
  "Effective risk": { ru: "Фактический риск", zh: "有效风险" },
  "Email": { ru: "Email", zh: "邮箱" },
  "Enabled": { ru: "Включено", zh: "已启用" },
  "Entry": { ru: "Вход", zh: "入场" },
  "Entry candidate inside": { ru: "Кандидат на вход в зоне", zh: "入场候选位于" },
  "Entry is blocked by backend risk gate.": { ru: "Вход заблокирован backend risk gate.", zh: "入场被后端风控网关阻止。" },
  "Entry Zone": { ru: "Зона входа", zh: "入场区间" },
  "Equity": { ru: "Equity", zh: "权益" },
  "evaluated": { ru: "проверено", zh: "已评估" },
  "Exchange": { ru: "Биржа", zh: "交易所" },
  "Exchange rules": { ru: "Правила биржи", zh: "交易所规则" },
  "Exchanges": { ru: "Биржи", zh: "交易所" },
  "Exec": { ru: "Исполнение", zh: "执行" },
  "Execution": { ru: "Исполнение", zh: "执行" },
  "Execution looks realistic for this virtual size.": { ru: "Исполнение выглядит реалистично для этого virtual-размера.", zh: "该 virtual 规模的执行看起来现实。" },
  "Expected slippage": { ru: "Ожидаемое slippage", zh: "预期滑点" },
  "Features": { ru: "Фичи", zh: "特征" },
  "Fee source": { ru: "Источник комиссии", zh: "费用来源" },
  "Fees included": { ru: "Комиссии учтены", zh: "已计入手续费" },
  "Fill": { ru: "Исполнение", zh: "成交" },
  "Filter rows": { ru: "Фильтр строк", zh: "筛选行" },
  "Filter target": { ru: "Цель фильтра", zh: "过滤目标" },
  "Final RR": { ru: "Итоговый RR", zh: "最终 RR" },
  "Final target": { ru: "Финальная цель", zh: "最终目标" },
  "Fixed": { ru: "Фикс.", zh: "固定" },
  "Fixed %": { ru: "Фикс. %", zh: "固定 %" },
  "Fixed stop": { ru: "Фикс. стоп", zh: "固定止损" },
  "Futures max lev.": { ru: "Макс. плечо futures", zh: "合约最大杠杆" },
  "Futures open risk": { ru: "Открытый риск futures", zh: "合约持仓风险" },
  "Futures Protection": { ru: "Защита futures", zh: "合约保护" },
  "Futures protection": { ru: "Защита futures", zh: "合约保护" },
  "Futures risk": { ru: "Риск futures", zh: "合约风险" },
  "Futures risk budget": { ru: "Риск-бюджет futures", zh: "合约风险预算" },
  "Global": { ru: "Глобально", zh: "全局" },
  "Good": { ru: "Хорошо", zh: "良好" },
  "Guide": { ru: "Гайд", zh: "指南" },
  "Hide Chart": { ru: "Скрыть график", zh: "隐藏图表" },
  "Hide low-RR cards": { ru: "Скрывать карточки с низким RR", zh: "隐藏低 RR 卡片" },
  "High": { ru: "Высокий", zh: "高" },
  "High Confidence": { ru: "Высокая уверенность", zh: "高置信" },
  "Ignore Signal": { ru: "Игнорировать сигнал", zh: "忽略信号" },
  "Impact": { ru: "Impact", zh: "冲击" },
  "Invalidation": { ru: "Инвалидация", zh: "失效" },
  "Journal": { ru: "Журнал", zh: "日志" },
  "Journal is empty": { ru: "Журнал пуст", zh: "日志为空" },
  "Keep stop loss": { ru: "Оставить stop loss", zh: "保留止损" },
  "Label": { ru: "Название", zh: "标签" },
  "Language": { ru: "Язык", zh: "语言" },
  "Last update": { ru: "Последнее обновление", zh: "最后更新" },
  "Level retests": { ru: "Ретесты уровня", zh: "水平重测" },
  "Limit": { ru: "Лимит", zh: "限价" },
  "Liq. buffer": { ru: "Буфер ликв.", zh: "强平缓冲" },
  "Liquidation buffer required": { ru: "Буфер ликвидации обязателен", zh: "需要强平缓冲" },
  "Liquidity": { ru: "Ликвидность", zh: "流动性" },
  "Liquidity Sweep": { ru: "Снятие ликвидности", zh: "流动性扫单" },
  "Live": { ru: "Live", zh: "在线" },
  "Live · Connected": { ru: "Online · Connected", zh: "在线 · 已连接" },
  "Live data delayed": { ru: "Live data delayed", zh: "实时数据延迟" },
  "Online · Connected": { ru: "Online · Connected", zh: "在线 · 已连接" },
  "Loading analytics...": { ru: "Загружаем аналитику...", zh: "正在加载分析..." },
  "Loading chart...": { ru: "Загружаем график...", zh: "正在加载图表..." },
  "Loading signals...": { ru: "Загружаем сигналы...", zh: "正在加载信号..." },
  "Loading table...": { ru: "Загружаем таблицу...", zh: "正在加载表格..." },
  "Loading watchlist": { ru: "Загружаем watchlist", zh: "正在加载观察列表" },
  "Low": { ru: "Низкий", zh: "低" },
  "Lower risk limits": { ru: "Более низкие лимиты риска", zh: "更低的风险限制" },
  "Manual limits": { ru: "Ручные лимиты", zh: "手动限制" },
  "Manual pair scope bypasses automatic quality exclusion.": {
    ru: "Ручной список пар обходит автоматическое исключение по качеству.",
    zh: "手动交易对范围会绕过自动质量排除。"
  },
  "Market / Limit": { ru: "Market / Limit", zh: "市价 / 限价" },
  "Market data": { ru: "Рыночные данные", zh: "市场数据" },
  "market data": { ru: "market data", zh: "市场数据" },
  "Market impact": { ru: "Влияние на рынок", zh: "市场冲击" },
  "Market opportunities": { ru: "Рыночные возможности", zh: "市场机会" },
  "Market order": { ru: "Market-ордер", zh: "市价单" },
  "Market quality": { ru: "Качество рынка", zh: "市场质量" },
  "Market regime": { ru: "Режим рынка", zh: "市场状态" },
  "Market Status": { ru: "Состояние рынка", zh: "市场状态" },
  "Mark price": { ru: "Mark price", zh: "标记价格" },
  "Max book use": { ru: "Макс. доля стакана", zh: "最大盘口占用" },
  "Max body ATR": { ru: "Макс. body ATR", zh: "最大实体 ATR" },
  "Max drawdown": { ru: "Макс. просадка", zh: "最大回撤" },
  "Max leverage": { ru: "Макс. плечо", zh: "最大杠杆" },
  "Max price drift": { ru: "Макс. уход цены", zh: "最大价格偏移" },
  "Max range ATR": { ru: "Макс. range ATR", zh: "最大区间 ATR" },
  "Max risk boost": { ru: "Макс. буст риска", zh: "最大风险提升" },
  "Max slippage": { ru: "Макс. slippage", zh: "最大滑点" },
  "Max spread": { ru: "Макс. spread", zh: "最大价差" },
  "Medium": { ru: "Средний", zh: "中" },
  "Min 24h volume": { ru: "Мин. объём 24ч", zh: "最小24小时成交量" },
  "Min history": { ru: "Мин. история", zh: "最小历史" },
  "Minimum RR": { ru: "Минимальный RR", zh: "最小 RR" },
  "Min R:R": { ru: "Мин. R:R", zh: "最小 R:R" },
  "Min RR": { ru: "Мин. RR", zh: "最小 RR" },
  "Min S/R ATR": { ru: "Мин. S/R ATR", zh: "最小支撑/阻力 ATR" },
  "Min wick": { ru: "Мин. фитиль", zh: "最小影线" },
  "mixed": { ru: "смешанный", zh: "混合" },
  "Mode": { ru: "Режим", zh: "模式" },
  "Model": { ru: "Модель", zh: "模型" },
  "Move after": { ru: "Перенос после", zh: "达到后移动" },
  "MVP demo session": { ru: "MVP demo-сессия", zh: "MVP 演示会话" },
  "Nearest RR": { ru: "Ближайший RR", zh: "最近 RR" },
  "Nearest target": { ru: "Ближайшая цель", zh: "最近目标" },
  "Net PnL": { ru: "Чистый PnL", zh: "净 PnL" },
  "New signals, trade lifecycle events, and exchange issues will appear here.": {
    ru: "Новые сигналы, события сделок и проблемы бирж появятся здесь.",
    zh: "新信号、交易生命周期事件和交易所问题会显示在这里。"
  },
  "No active signals yet": { ru: "Активных сигналов пока нет", zh: "暂无活跃信号" },
  "No active trades": { ru: "Активных сделок нет", zh: "暂无活跃交易" },
  "No alert rules": { ru: "Правил алертов нет", zh: "暂无提醒规则" },
  "No candle data for this trade": { ru: "Нет свечных данных для этой сделки", zh: "该交易暂无K线数据" },
  "No exchange connections": { ru: "Подключений бирж нет", zh: "暂无交易所连接" },
  "No historical signals yet": { ru: "Исторических сигналов пока нет", zh: "暂无历史信号" },
  "No notifications yet": { ru: "Уведомлений пока нет", zh: "暂无通知" },
  "No pairs": { ru: "Пар нет", zh: "暂无交易对" },
  "No pairs in watchlist": { ru: "В watchlist нет пар", zh: "观察列表暂无交易对" },
  "No plans": { ru: "Планов нет", zh: "暂无套餐" },
  "No renewal date": { ru: "Нет даты продления", zh: "无续订日期" },
  "No rows": { ru: "Строк нет", zh: "暂无行" },
  "No scanner series": { ru: "Серий сканера нет", zh: "暂无扫描序列" },
  "No signals": { ru: "Сигналов нет", zh: "暂无信号" },
  "No strategy configs": { ru: "Нет настроек стратегий", zh: "暂无策略配置" },
  "No trades": { ru: "Сделок нет", zh: "暂无交易" },
  "None": { ru: "Нет", zh: "无" },
  "Not recommended": { ru: "Не рекомендуется", zh: "不建议" },
  "New signal": { ru: "Новый сигнал", zh: "新信号" },
  "Notifications": { ru: "Уведомления", zh: "通知" },
  "Offline": { ru: "Offline", zh: "离线" },
  "Offset": { ru: "Отступ", zh: "偏移" },
  "On": { ru: "On", zh: "开" },
  "Off": { ru: "Off", zh: "关" },
  "Online": { ru: "Online", zh: "在线" },
  "Open": { ru: "Открытые", zh: "开放" },
  "Open Exchange": { ru: "Открыть биржу", zh: "打开交易所" },
  "Open positions": { ru: "Открытые позиции", zh: "持仓" },
  "Open risk": { ru: "Открытый риск", zh: "持仓风险" },
  "Open risk cap": { ru: "Лимит открытого риска", zh: "持仓风险上限" },
  "Orderbook": { ru: "Стакан", zh: "订单簿" },
  "Order type": { ru: "Тип ордера", zh: "订单类型" },
  "Pair": { ru: "Пара", zh: "交易对" },
  "Pairs": { ru: "Пары", zh: "交易对" },
  "Paper Trade": { ru: "Paper-сделка", zh: "Paper 交易" },
  "Passphrase": { ru: "Passphrase", zh: "口令" },
  "Partial": { ru: "Частично", zh: "部分" },
  "Partial take-profit": { ru: "Частичный take-profit", zh: "部分止盈" },
  "Passive": { ru: "Пассивно", zh: "被动" },
  "Password": { ru: "Пароль", zh: "密码" },
  "Pending": { ru: "Ожидание", zh: "等待" },
  "planned retest": { ru: "запланированный retest", zh: "计划重测" },
  "Plans": { ru: "Планы", zh: "套餐" },
  "Portal": { ru: "Портал", zh: "门户" },
  "Position size": { ru: "Размер позиции", zh: "仓位规模" },
  "Post-impact": { ru: "После impact", zh: "冲击后" },
  "Preparing": { ru: "Подготовка", zh: "准备中" },
  "Preview error": { ru: "Ошибка preview", zh: "预览错误" },
  "Preview pending": { ru: "Preview ожидает", zh: "预览等待中" },
  "Price": { ru: "Цена", zh: "价格" },
  "Price above": { ru: "Цена выше", zh: "价格高于" },
  "Price below": { ru: "Цена ниже", zh: "价格低于" },
  "Price drift": { ru: "Уход цены", zh: "价格偏移" },
  "Price is testing previous swing high; waiting for liquidity sweep and rejection": {
    ru: "Цена тестирует предыдущий swing high; ждём liquidity sweep и rejection",
    zh: "价格正在测试前一个 swing high；等待 liquidity sweep 和 rejection"
  },
  "Price is testing previous swing low; waiting for liquidity sweep and reclaim": {
    ru: "Цена тестирует предыдущий swing low; ждём liquidity sweep и reclaim",
    zh: "价格正在测试前一个 swing low；等待 liquidity sweep 和 reclaim"
  },
  "Pro": { ru: "Pro", zh: "专业" },
  "Protection": { ru: "Защита", zh: "保护" },
  "Pullback Wait": { ru: "Ожидание pullback", zh: "等待回调" },
  "Queue, fees, liquidity": { ru: "Очередь, комиссии, ликвидность", zh: "队列、费用、流动性" },
  "Radar": { ru: "Радар", zh: "雷达" },
  "Radar settings": { ru: "Настройки радара", zh: "雷达设置" },
  "Read all": { ru: "Прочитать всё", zh: "全部已读" },
  "Real": { ru: "Real", zh: "实盘" },
  "Realistic execution": { ru: "Реалистичное исполнение", zh: "真实执行模拟" },
  "Realtime events": { ru: "Realtime-события", zh: "实时事件" },
  "Realized PnL": { ru: "Реализованный PnL", zh: "已实现 PnL" },
  "Reality Check": { ru: "Проверка реальности", zh: "现实检查" },
  "Reconnecting...": { ru: "Переподключение...", zh: "重新连接..." },
  "Redirecting to sign in": { ru: "Переходим ко входу", zh: "正在跳转登录" },
  "Refresh": { ru: "Обновить", zh: "刷新" },
  "Replay, Monte Carlo": { ru: "Replay, Monte Carlo", zh: "回放，蒙特卡洛" },
  "Risk": { ru: "Риск", zh: "风险" },
  "Risk / Reward": { ru: "Риск / прибыль", zh: "风险 / 收益" },
  "Risk / Reward Filter": { ru: "Фильтр Risk / Reward", zh: "风险收益过滤" },
  "Risk / trade": { ru: "Риск / сделка", zh: "单笔风险" },
  "Risk budget": { ru: "Риск-бюджет", zh: "风险预算" },
  "Risk gate": { ru: "Risk gate", zh: "风控网关" },
  "Risk management": { ru: "Risk management", zh: "风险管理" },
  "Risk Management": { ru: "Risk management", zh: "风险管理" },
  "Risk multiple": { ru: "Risk multiple", zh: "风险倍数" },
  "Risk Profile": { ru: "Профиль риска", zh: "风险配置" },
  "Risk size": { ru: "Размер риска", zh: "风险规模" },
  "Risk multiplier": { ru: "Множитель риска", zh: "风险倍数" },
  "Risky": { ru: "Рискованно", zh: "有风险" },
  "RR 1": { ru: "RR 1", zh: "RR 1" },
  "RR target": { ru: "RR-цель", zh: "RR 目标" },
  "Safe size": { ru: "Безопасный размер", zh: "安全规模" },
  "Save custom": { ru: "Сохранить свои", zh: "保存自定义" },
  "Scanner activity": { ru: "Активность сканера", zh: "扫描器活动" },
  "scanner": { ru: "сканер", zh: "扫描器" },
  "Scanner live": { ru: "Сканер Online", zh: "扫描器运行中" },
  "Scanner offline": { ru: "Сканер Offline", zh: "扫描器离线" },
  "Scanner status unknown": { ru: "Статус сканера неизвестен", zh: "扫描器状态未知" },
  "Scanner stopping": { ru: "Сканер останавливается", zh: "扫描器停止中" },
  "Score": { ru: "Скор", zh: "评分" },
  "Seeded candles": { ru: "Загружено свечей", zh: "预置K线" },
  "Selected RR": { ru: "Выбранный RR", zh: "选定 RR" },
  "Select pair": { ru: "Выбрать пару", zh: "选择交易对" },
  "Series": { ru: "Серия", zh: "序列" },
  "Settings": { ru: "Настройки", zh: "设置" },
  "Setup exists, wait for confirmation": { ru: "Setup есть, ждём подтверждение", zh: "Setup 已形成，等待确认" },
  "Show Chart": { ru: "Показать график", zh: "显示图表" },
  "Side": { ru: "Сторона", zh: "方向" },
  "Signal": { ru: "Сигнал", zh: "信号" },
  "Signal Details": { ru: "Детали сигнала", zh: "信号详情" },
  "Signal Feed": { ru: "Лента сигналов", zh: "信号流" },
  "Signal First Radar": { ru: "Радар сигналов", zh: "信号优先雷达" },
  "Signal generated": { ru: "Сигнал создан", zh: "信号生成" },
  "Signals found": { ru: "Найдено сигналов", zh: "发现信号" },
  "Signing in": { ru: "Входим", zh: "登录中" },
  "Sign in": { ru: "Войти", zh: "登录" },
  "Simple MVP stop": { ru: "Простой MVP-стоп", zh: "简单 MVP 止损" },
  "Simulation": { ru: "Симуляция", zh: "模拟" },
  "Slippage included": { ru: "Slippage учтено", zh: "已计入滑点" },
  "Sound": { ru: "Звук", zh: "声音" },
  "Speculative": { ru: "Спекулятивный", zh: "投机" },
  "Spot max size": { ru: "Макс. размер spot", zh: "现货最大规模" },
  "Spot risk": { ru: "Риск spot", zh: "现货风险" },
  "Spot stop required": { ru: "Spot stop обязателен", zh: "现货需要止损" },
  "Spread": { ru: "Spread", zh: "价差" },
  "Status": { ru: "Статус", zh: "状态" },
  "Stop": { ru: "Стоп", zh: "止损" },
  "Stop Loss": { ru: "Stop Loss", zh: "止损" },
  "Stop required": { ru: "Стоп обязателен", zh: "需要止损" },
  "Stop scanner": { ru: "Остановить сканер", zh: "停止扫描器" },
  "Stop-loss": { ru: "Stop-loss", zh: "止损" },
  "Strategies": { ru: "Стратегии", zh: "策略" },
  "Strategy Checks": { ru: "Проверки стратегий", zh: "策略检查" },
  "Strategy invalidation": { ru: "Инвалидация стратегии", zh: "策略失效" },
  "Strategy Layers": { ru: "Слои стратегии", zh: "策略层" },
  "Strategy multipliers": { ru: "Множители стратегий", zh: "策略倍数" },
  "Strategy setup": { ru: "Strategy setup", zh: "策略 setup" },
  "Structure": { ru: "Структура", zh: "结构" },
  "Subscription": { ru: "Подписка", zh: "订阅" },
  "Sweep volume x": { ru: "Объём sweep x", zh: "扫单成交量 x" },
  "Sync": { ru: "Синхронизировать", zh: "同步" },
  "Taker fee": { ru: "Taker fee", zh: "Taker 手续费" },
  "Take Profit": { ru: "Take Profit", zh: "止盈" },
  "Take-profit": { ru: "Take-profit", zh: "止盈" },
  "Test": { ru: "Тест", zh: "测试" },
  "TF": { ru: "TF", zh: "周期" },
  "The scanner may still be building candle history, or the market has not produced a valid setup.": {
    ru: "Сканер может ещё собирать историю свечей, или рынок пока не дал валидный setup.",
    zh: "扫描器可能仍在构建K线历史，或市场尚未形成有效 setup。"
  },
  "Timeframes": { ru: "Таймфреймы", zh: "时间周期" },
  "Ticks": { ru: "Тики", zh: "Ticks" },
  "Total Trades": { ru: "Всего сделок", zh: "总交易数" },
  "Top MVP pairs": { ru: "Топ MVP-пары", zh: "MVP 热门交易对" },
  "Trade Rules": { ru: "Правила сделок", zh: "交易规则" },
  "Trades": { ru: "Сделки", zh: "交易" },
  "Trades and journal": { ru: "Сделки и журнал", zh: "交易与日志" },
  "Trading actions disabled": { ru: "Торговые действия отключены", zh: "交易操作已禁用" },
  "Trading actions disabled until realtime data is current.": {
    ru: "Торговые действия отключены, пока realtime-данные не станут актуальными.",
    zh: "在实时数据恢复最新前，交易操作已禁用。"
  },
  "Trailing": { ru: "Trailing", zh: "追踪" },
  "Trailing stop": { ru: "Trailing stop", zh: "追踪止损" },
  "Trend": { ru: "Тренд", zh: "趋势" },
  "Trend pullback": { ru: "Trend pullback", zh: "趋势回调" },
  "Two-factor check": { ru: "Проверка 2FA", zh: "双因素验证" },
  "Updated": { ru: "Обновлено", zh: "更新时间" },
  "Use Auto Paper to wait for confirmation and enter automatically after the trigger candle.": {
    ru: "Используйте Auto Paper, чтобы дождаться подтверждения и войти автоматически после триггерной свечи.",
    zh: "使用 Auto Paper 等待确认，并在触发K线后自动入场。"
  },
  "Use smaller size": { ru: "Уменьшить размер", zh: "使用更小规模" },
  "Virtual": { ru: "Virtual", zh: "模拟" },
  "Virtual balance": { ru: "Virtual баланс", zh: "模拟余额" },
  "Virtual execution": { ru: "Virtual исполнение", zh: "模拟执行" },
  "Virtual risk": { ru: "Virtual риск", zh: "模拟风险" },
  "Virtual risk budget": { ru: "Virtual риск-бюджет", zh: "模拟风险预算" },
  "Virtual Trading": { ru: "Virtual trading", zh: "模拟交易" },
  "Virtual Trades": { ru: "Virtual-сделки", zh: "模拟交易" },
  "Volatility": { ru: "Волатильность", zh: "波动率" },
  "Volume": { ru: "Объём", zh: "成交量" },
  "Volume x": { ru: "Объём x", zh: "成交量 x" },
  "Waiting": { ru: "Ожидание", zh: "等待" },
  "Waiting for market data": { ru: "Ждём рыночные данные", zh: "等待市场数据" },
  "Waiting for stream": { ru: "Ждём stream", zh: "等待数据流" },
  "Watch setup formation, no entry yet": { ru: "Наблюдать за формированием setup, входа пока нет", zh: "观察 setup 形成，暂不入场" },
  "Watchlist": { ru: "Список", zh: "观察列表" },
  "Weekly": { ru: "Неделя", zh: "周" },
  "Why this signal?": { ru: "Почему этот сигнал?", zh: "为什么是这个信号？" },
  "Win Rate": { ru: "Win Rate", zh: "胜率" },
  "Actionable entry follows the current strategy status; retest is the conservative alternative.": {
    ru: "Вход зависит от текущего статуса стратегии; ретест остается консервативной альтернативой.",
    zh: "入场跟随当前策略状态；回测区是保守替代方案。"
  },
  "Actionable entry is the retest zone while the breakout candle cools off.": {
    ru: "Рабочая зона входа сейчас находится на ретесте, пока breakout-свеча остывает.",
    zh: "突破K线冷却期间，可执行入场位于回测区。"
  },
  "ATR value is unavailable; using trailing percent fallback.": {
    ru: "ATR недоступен; используем резервный процентный трейлинг.",
    zh: "ATR 不可用；使用追踪百分比回退。"
  },
  "Bid / Ask": { ru: "Бид / аск", zh: "买价 / 卖价" },
  "Chart": { ru: "График", zh: "图表" },
  "Chart:": { ru: "График:", zh: "图表:" },
  "conservative_fallback": { ru: "консервативный резерв", zh: "保守回退" },
  "Confirm zone": { ru: "Зона подтверждения", zh: "确认区间" },
  "Confirmation": { ru: "Подтверждение", zh: "确认" },
  "Confirmation Checklist": { ru: "Чек-лист подтверждения", zh: "确认清单" },
  "context resistance": { ru: "Контекстное сопротивление", zh: "上下文阻力" },
  "context support": { ru: "Контекстная поддержка", zh: "上下文支撑" },
  "context timeframe": { ru: "Контекстный TF", zh: "上下文周期" },
  "ema200 chop": { ru: "EMA200 chop", zh: "EMA200 震荡" },
  "Execution": { ru: "Исполнение", zh: "执行" },
  "Execution:": { ru: "Исполнение:", zh: "执行:" },
  "Exit management": { ru: "Управление выходом", zh: "退出管理" },
  "Exit plan": { ru: "План выхода", zh: "退出计划" },
  "Entry is blocked by backend risk gate.": { ru: "Вход заблокирован серверным риск-гейтом.", zh: "入场被后端风控网关阻止。" },
  "Entry, SL and TP are calculated": { ru: "Вход, SL и TP рассчитаны", zh: "入场、SL 和 TP 已计算" },
  "Funding buffer": { ru: "Буфер funding", zh: "资金费缓冲" },
  "Futures guard": { ru: "Futures-защита", zh: "合约保护" },
  "Level touches": { ru: "Касания уровня", zh: "水平触碰" },
  "Margin": { ru: "Маржа", zh: "保证金" },
  "Mark price": { ru: "Маркировочная цена", zh: "标记价格" },
  "Measured move": { ru: "Цель measured move", zh: "量度目标" },
  "News/Event Risk": { ru: "Новостной/ивент-риск", zh: "新闻/事件风险" },
  "Overheat Penalty": { ru: "Штраф за перегрев", zh: "过热惩罚" },
  "Planned stop": { ru: "Плановый стоп", zh: "计划止损" },
  "Preview pending": { ru: "Ожидает расчёт", zh: "预览等待中" },
  "Recommended action": { ru: "Рекомендованное действие", zh: "建议操作" },
  "regime alignment": { ru: "Режим", zh: "市场状态" },
  "regime strength": { ru: "Сила режима", zh: "状态强度" },
  "reduced": { ru: "сниженная", zh: "降低" },
  "Retest zone": { ru: "Зона ретеста", zh: "回测区" },
  "Risks": { ru: "Риски", zh: "风险" },
  "Risk / Reward Filter": { ru: "Фильтр риска/прибыли", zh: "风险收益过滤" },
  "Risk gate": { ru: "Риск-гейт", zh: "风控网关" },
  "Risk/Reward is set": { ru: "RR указан", zh: "Risk/Reward 已设置" },
  "Risk/Reward": { ru: "Риск/прибыль", zh: "风险收益" },
  "Spread": { ru: "Спред", zh: "价差" },
  "Signal:": { ru: "Сигнал:", zh: "信号:" },
  "Stop Loss": { ru: "Стоп-лосс", zh: "止损" },
  "Strategy setup exists, but confirmation is incomplete": {
    ru: "Setup стратегии есть, но подтверждение неполное",
    zh: "策略 setup 已形成，但确认尚未完成"
  },
  "Strategy setup": { ru: "Сетап стратегии", zh: "策略 setup" },
  "Sweep is actionable only after reclaim, wick, volume and RR checks stay valid.": {
    ru: "Sweep можно отрабатывать только после reclaim, если фитиль, объём и RR остаются валидными.",
    zh: "只有在重新收复后，且影线、成交量和 RR 检查仍有效时，扫单才可执行。"
  },
  "Sweep is staged; wait for reclaim or a confirmation candle through micro structure.": {
    ru: "Sweep подготовлен; дождитесь reclaim или подтверждающей свечи через микроструктуру.",
    zh: "扫单已进入准备阶段；等待重新收复或穿越微结构的确认K线。"
  },
  "Swept level": { ru: "Снятый уровень", zh: "被扫水平" },
  "Take Profit": { ru: "Тейк-профит", zh: "止盈" },
  "Taker fee": { ru: "Taker-комиссия", zh: "吃单手续费" },
  "Trailing": { ru: "Трейлинг", zh: "追踪止损" },
  "Wait for pullback or retest": { ru: "Ждать pullback или ретест", zh: "等待回调或回测" },
  "Wick": { ru: "Фитиль", zh: "影线" },
  "active": { ru: "активен", zh: "活跃" },
  "actionable": { ru: "можно входить", zh: "可入场" },
  "all": { ru: "все", zh: "全部" },
  "blocked": { ru: "заблокировано", zh: "已阻止" },
  "closed": { ru: "закрыта", zh: "已关闭" },
  "confirmed": { ru: "подтверждён", zh: "已确认" },
  "entry touched": { ru: "вход задет", zh: "触及入场" },
  "expired": { ru: "истёк", zh: "已过期" },
  "failed": { ru: "ошибка", zh: "失败" },
  "final": { ru: "финальная", zh: "最终" },
  "Forming": { ru: "Формируется", zh: "形成中" },
  "fresh": { ru: "актуально", zh: "新鲜" },
  "good": { ru: "хороший", zh: "良好" },
  "history": { ru: "история", zh: "历史" },
  "invalidated": { ru: "сломана", zh: "已失效" },
  "low": { ru: "низкий", zh: "低" },
  "medium": { ru: "средний", zh: "中" },
  "nearest": { ru: "ближайшая", zh: "最近" },
  "new": { ru: "новый", zh: "新" },
  "none": { ru: "нет", zh: "无" },
  "open": { ru: "открытые", zh: "开放" },
  "open ideas": { ru: "открытые идеи", zh: "开放想法" },
  "passed": { ru: "пройдено", zh: "通过" },
  "pending": { ru: "ожидание", zh: "等待" },
  "poor": { ru: "слабое", zh: "差" },
  "ready": { ru: "готов", zh: "就绪" },
  "rejected": { ru: "отклонён", zh: "已拒绝" },
  "risky": { ru: "рискованное", zh: "有风险" },
  "short": { ru: "SHORT", zh: "SHORT" },
  "long": { ru: "LONG", zh: "LONG" },
  "strong": { ru: "сильный", zh: "强" },
  "stub": { ru: "заглушка", zh: "占位" },
  "unknown": { ru: "неизвестно", zh: "未知" },
  "virtual": { ru: "virtual", zh: "模拟" },
  "wait for pullback": { ru: "ждём pullback", zh: "等待回调" },
  "watchlist": { ru: "наблюдение", zh: "观察" },
  "warning": { ru: "предупреждение", zh: "警告" },
  "no": { ru: "нет", zh: "否" },
  "yes": { ru: "да", zh: "是" }
};

export function translatePhrase(value: string, locale: Locale): string {
  if (locale === "en") return phrases[value]?.en ?? value;
  return phrases[value]?.[locale] ?? value;
}

export function translateText(value: string, locale: Locale): string {
  const normalized = value.replace(/\s+/g, " ").trim();
  if (!normalized) return value;

  const exact = translatePhrase(normalized, locale);
  if (exact !== normalized) return withOriginalWhitespace(value, exact);

  const dynamic = translateDynamicText(normalized, locale);
  if (dynamic !== normalized) return withOriginalWhitespace(value, dynamic);

  return value;
}

function withOriginalWhitespace(original: string, translated: string): string {
  const leading = original.match(/^\s*/)?.[0] ?? "";
  const trailing = original.match(/\s*$/)?.[0] ?? "";
  return `${leading}${translated}${trailing}`;
}

function translateDynamicText(value: string, locale: Locale): string {
  const tradingText = translateTradingText(value, locale);
  if (tradingText !== value) return tradingText;

  const replacements: Array<[RegExp, (match: RegExpMatchArray) => string]> = [
    [/^Browser: (.+)$/u, (match) => `${translatePhrase("Browser", locale)}: ${translatePhrase(match[1] ?? "", locale)}`],
    [/^Current (.+)$/u, (match) => `${translatePhrase("Current", locale)} ${match[1] ?? ""}`],
    [/^Daily (.+)$/u, (match) => `${translatePhrase("Daily", locale)} ${match[1] ?? ""}`],
    [/^Drawdown (.+)$/u, (match) => `${translatePhrase("Drawdown", locale)} ${match[1] ?? ""}`],
    [/^Entry candidate inside (.+)$/u, (match) => `${translatePhrase("Entry candidate inside", locale)} ${match[1] ?? ""}`],
    [/^Features built: (.+)$/u, (match) => `${translatePhrase("Features", locale)}: ${match[1] ?? ""}`],
    [/^Last update: (.+)$/u, (match) => `${translatePhrase("Last update", locale)}: ${translateAge(match[1] ?? "", locale)}`],
    [/^Open (.+)$/u, (match) => `${translatePhrase("Open", locale)} ${match[1] ?? ""}`],
    [/^Pairs: (.+)$/u, (match) => `${translatePhrase("Pairs", locale)}: ${match[1] ?? ""}`],
    [/^Protection: (.+)$/u, (match) => `${translatePhrase("Protection", locale)}: ${translatePhrase(match[1] ?? "", locale)}`],
    [/^Risk: (.+)$/u, (match) => `${translatePhrase("Risk", locale)}: ${translatePhrase(match[1] ?? "", locale)}`],
    [/^Seeded candles: (.+)$/u, (match) => `${translatePhrase("Seeded candles", locale)}: ${match[1] ?? ""}`],
    [/^Signal: (.+)$/u, (match) => `${translatePhrase("Signal", locale)}: ${translatePhrase(match[1] ?? "", locale)}`],
    [/^Chart: (.+)$/u, (match) => `${translatePhrase("Chart", locale)}: ${translatePhrase(match[1] ?? "", locale)}`],
    [/^Execution: (.+)$/u, (match) => `${translatePhrase("Execution", locale)}: ${translatePhrase(match[1] ?? "", locale)}`],
    [/^Signals found: (.+)$/u, (match) => `${translatePhrase("Signals found", locale)}: ${match[1] ?? ""}`],
    [/^Strategy status: (.+)$/u, (match) => `${translatePhrase("Status", locale)} стратегии: ${translatePhrase(match[1] ?? "", locale)}`],
    [/^Timeframes: (.+)$/u, (match) => `${translatePhrase("Timeframes", locale)}: ${match[1] ?? ""}`],
    [/^TTL expired$/u, () => (locale === "zh" ? "TTL 已过期" : locale === "ru" ? "TTL истёк" : "TTL expired")],
    [/^TTL n\/a$/u, () => (locale === "zh" ? "TTL 不可用" : locale === "ru" ? "TTL н/д" : "TTL n/a")],
    [/^TTL (.+)$/u, (match) => `TTL ${translateAge(match[1] ?? "", locale)}`],
    [/^Updated (.+)$/u, (match) => `${translatePhrase("Updated", locale)} ${match[1] ?? ""}`],
    [/^Weekly (.+)$/u, (match) => `${translatePhrase("Weekly", locale)} ${match[1] ?? ""}`],
    [/^(\d+) candles$/u, (match) => (locale === "zh" ? `${match[1]} 根K线` : locale === "ru" ? `${match[1]} свечей` : value)],
    [/^(\d+) rows$/u, (match) => (locale === "zh" ? `${match[1]} 行` : locale === "ru" ? `${match[1]} строк` : value)],
    [/^(\d+) selected pairs$/u, (match) => (locale === "zh" ? `已选交易对: ${match[1]}` : locale === "ru" ? `Выбрано пар: ${match[1]}` : value)],
    [/^Page size (.+)$/u, (match) => (locale === "zh" ? `每页 ${match[1]}` : locale === "ru" ? `Размер страницы ${match[1]}` : value)],
    [/^Risk (Low|Medium|High|Speculative)$/u, (match) => `${translatePhrase("Risk", locale)} ${translatePhrase(match[1] ?? "", locale)}`],
    [/^(\d+)% Confidence$/u, (match) => (locale === "zh" ? `置信度 ${match[1]}%` : locale === "ru" ? `Уверенность ${match[1]}%` : value)],
    [/^(.+) Signal$/u, (match) => `${match[1] ?? ""} ${translatePhrase("Signal", locale)}`],
    [/^(\d+) Targets$/u, (match) => (locale === "zh" ? `${match[1]} 个目标` : locale === "ru" ? `${match[1]} цели` : value)]
  ];

  for (const [pattern, replacement] of replacements) {
    const match = value.match(pattern);
    if (match) return replacement(match);
  }

  return value;
}

function translateTradingText(value: string, locale: Locale): string {
  if (locale === "en") return value;

  const exact = tradeTextMap[value];
  if (exact) return exact[locale] ?? value;

  const riskReward = value.match(/^Risk\/reward passed: (nearest|final) target is ([\d.]+R), minimum ([\d.]+R)$/u);
  if (riskReward) {
    const target = riskReward[1] === "nearest"
      ? translatePhrase("nearest", locale)
      : translatePhrase("final", locale);
    if (locale === "zh") return `Risk/reward 已通过: ${target}目标 ${riskReward[2]}, 最小 ${riskReward[3]}`;
    return `Риск/прибыль пройдены: ${target} цель ${riskReward[2]}, минимум ${riskReward[3]}`;
  }

  const plannedRiskReward = value.match(/^Risk\/reward passed: planned (nearest|final) target is ([\d.]+R), minimum ([\d.]+R)$/u);
  if (plannedRiskReward) {
    const target = plannedRiskReward[1] === "nearest"
      ? translatePhrase("nearest", locale)
      : translatePhrase("final", locale);
    if (locale === "zh") return `Risk/reward 已通过: 计划${target}目标 ${plannedRiskReward[2]}, 最小 ${plannedRiskReward[3]}`;
    return `Риск/прибыль пройдены: плановая ${target} цель ${plannedRiskReward[2]}, минимум ${plannedRiskReward[3]}`;
  }

  if (locale === "zh") {
    const levelQualityZh = value.match(/^Level quality: (.+) from 20-50 candle structure$/u);
    if (levelQualityZh) return `水平质量: ${levelQualityZh[1]} 来自 20-50 根K线结构`;

    const sweptLevelZh = value.match(/^Swept liquidity level: (.+)$/u);
    if (sweptLevelZh) return `被扫流动性水平: ${sweptLevelZh[1]}`;

    if (/^context timeframe: Expected none context; using signal timeframe only$/u.test(value)) {
      return "上下文周期: 未设置上下文，仅使用信号周期";
    }

    const regimeAlignmentZh = value.match(/^regime alignment: (long|short) vs (bullish|bearish|range|unknown) context \((weak|normal|strong|unknown)\)$/u);
    if (regimeAlignmentZh) {
      const side = regimeAlignmentZh[1]?.toUpperCase() ?? "";
      const regime = translateMarketEnum(regimeAlignmentZh[2] ?? "", locale);
      const strength = translateMarketEnum(regimeAlignmentZh[3] ?? "", locale);
      return `市场状态: ${side} 对 ${regime} 上下文 (${strength})`;
    }

    const regimeStrengthZh = value.match(/^regime strength: Higher timeframe trend strength is (weak|normal|strong|unknown)$/u);
    if (regimeStrengthZh) {
      const strength = translateMarketEnum(regimeStrengthZh[1] ?? "", locale);
      return `状态强度: 高周期趋势强度为 ${strength}`;
    }

    const sizeConsumeZh = value.match(/^Your size would consume (.+)\. Real entry could be worse by about (.+), and stop execution could add about (.+) friction\.$/u);
    if (sizeConsumeZh) {
      return `你的规模会消耗 ${translateLiquidityDepth(sizeConsumeZh[1] ?? "", locale)}。真实入场可能恶化约 ${sizeConsumeZh[2]}，止损执行可能额外增加约 ${sizeConsumeZh[3]} 摩擦。`;
    }

    const reduceRecommendationZh = value.match(/^Recommendation: reduce position size to about \$(.+), use a limit order, or skip the trade\.$/u);
    if (reduceRecommendationZh) {
      return `建议: 将仓位规模降至约 $${reduceRecommendationZh[1]}，使用限价单，或跳过这笔交易。`;
    }

    const skipRecommendationZh = value.match(/^Recommendation: skip this trade or use a much smaller (.+) setup\.$/u);
    if (skipRecommendationZh) {
      return `建议: 跳过这笔交易，或使用更小的 ${skipRecommendationZh[1]} setup。`;
    }

    const preferRecommendationZh = value.match(/^Recommendation: prefer (.+), reduce size if the book thins out, and avoid chasing a market order\.$/u);
    if (preferRecommendationZh) {
      return `建议: 优先使用 ${preferRecommendationZh[1]}，如果盘口变薄就降低规模，并避免追市价单。`;
    }
  }

  const levelQuality = value.match(/^Level quality: (.+) from 20-50 candle structure$/u);
  if (levelQuality) {
    if (locale === "zh") return `质量 уровня: ${levelQuality[1]} по структуре 20-50 свечей`;
    return `Качество уровня: ${levelQuality[1]} по структуре 20-50 свечей`;
  }

  const recentTouches = value.match(/^Level has (\d+) recent touches$/u);
  if (recentTouches) {
    if (locale === "zh") return `该水平最近有 ${recentTouches[1]} 次触碰`;
    return `У уровня ${recentTouches[1]} недавних касаний`;
  }

  const sweptLevel = value.match(/^Swept liquidity level: (.+)$/u);
  if (sweptLevel) {
    if (locale === "zh") return `Снят уровень ликвидности: ${sweptLevel[1]}`;
    return `Снят уровень ликвидности: ${sweptLevel[1]}`;
  }

  const status = value.match(/^Status: (.+)$/u);
  if (status) {
    const translatedStatus = translateTradingText(status[1] ?? "", locale);
    return `${translatePhrase("Status", locale)}: ${translatedStatus}`;
  }

  const contextTimeframe = value.match(/^context timeframe: Expected none context; using signal timeframe only$/u);
  if (contextTimeframe) {
    return locale === "zh"
      ? "Контекстный TF: контекст не задан, используется только TF сигнала"
      : "Контекстный TF: контекст не задан, используется только TF сигнала";
  }

  const regimeAlignment = value.match(/^regime alignment: (long|short) vs (bullish|bearish|range|unknown) context \((weak|normal|strong|unknown)\)$/u);
  if (regimeAlignment) {
    const side = regimeAlignment[1]?.toUpperCase() ?? "";
    const regime = translateMarketEnum(regimeAlignment[2] ?? "", locale);
    const strength = translateMarketEnum(regimeAlignment[3] ?? "", locale);
    return locale === "zh"
      ? `市场状态: ${side} 对上下文 ${regime} (${strength})`
      : `Режим: ${side} против контекста: ${regime} (${strength})`;
  }

  const regimeStrength = value.match(/^regime strength: Higher timeframe trend strength is (weak|normal|strong|unknown)$/u);
  if (regimeStrength) {
    const strength = translateMarketEnum(regimeStrength[1] ?? "", locale);
    return locale === "zh"
      ? `Сила режима: тренд старшего TF ${strength}`
      : `Сила режима: тренд старшего TF ${strength}`;
  }

  const sizeConsume = value.match(/^Your size would consume (.+)\. Real entry could be worse by about (.+), and stop execution could add about (.+) friction\.$/u);
  if (sizeConsume) {
    if (locale === "zh") {
      return `Ваш размер занял бы ${translateLiquidityDepth(sizeConsume[1] ?? "", locale)}. Реальный вход может быть хуже примерно на ${sizeConsume[2]}, а исполнение стопа может добавить около ${sizeConsume[3]} трения.`;
    }
    return `Ваш размер занял бы ${translateLiquidityDepth(sizeConsume[1] ?? "", locale)}. Реальный вход может быть хуже примерно на ${sizeConsume[2]}, а исполнение стопа может добавить около ${sizeConsume[3]} трения.`;
  }

  const reduceRecommendation = value.match(/^Recommendation: reduce position size to about \$(.+), use a limit order, or skip the trade\.$/u);
  if (reduceRecommendation) {
    if (locale === "zh") return `Рекомендация: уменьшить размер позиции примерно до $${reduceRecommendation[1]}, использовать limit-ордер или пропустить сделку.`;
    return `Рекомендация: уменьшить размер позиции примерно до $${reduceRecommendation[1]}, использовать limit-ордер или пропустить сделку.`;
  }

  const skipRecommendation = value.match(/^Recommendation: skip this trade or use a much smaller (.+) setup\.$/u);
  if (skipRecommendation) {
    if (locale === "zh") return `Рекомендация: пропустить сделку или использовать намного меньший ${skipRecommendation[1]} setup.`;
    return `Рекомендация: пропустить сделку или использовать намного меньший ${skipRecommendation[1]} setup.`;
  }

  const preferRecommendation = value.match(/^Recommendation: prefer (.+), reduce size if the book thins out, and avoid chasing a market order\.$/u);
  if (preferRecommendation) {
    if (locale === "zh") return `Рекомендация: предпочесть ${preferRecommendation[1]}, уменьшить размер при истончении стакана и не догонять market-ордер.`;
    return `Рекомендация: предпочесть ${preferRecommendation[1]}, уменьшить размер при истончении стакана и не догонять market-ордер.`;
  }

  const realisticSize = value.match(/^The requested size fits current liquidity with expected entry slippage around (.+)\.$/u);
  if (realisticSize) {
    if (locale === "zh") return `请求规模符合当前流动性，预期入场滑点约 ${realisticSize[1]}。`;
    return `Запрошенный размер помещается в текущую ликвидность; ожидаемое slippage входа около ${realisticSize[1]}.`;
  }

  const sensitiveSetup = value.match(/^The setup is tradable, but execution is sensitive: expected entry slippage is (.+) and impact risk is (.+)\.$/u);
  if (sensitiveSetup) {
    const impact = translatePhrase(sensitiveSetup[2] ?? "", locale);
    if (locale === "zh") return `Setup 可交易，但执行较敏感：预期入场滑点 ${sensitiveSetup[1]}，impact 风险 ${impact}。`;
    return `Setup можно торговать, но исполнение чувствительно: ожидаемое slippage входа ${sensitiveSetup[1]}, impact-риск ${impact}.`;
  }

  const rejectionWick = value.match(/^Rejection wick ratio is (.+)$/u);
  if (rejectionWick) {
    if (locale === "zh") return `拒绝影线比例为 ${rejectionWick[1]}`;
    return `Доля rejection-фитиля ${rejectionWick[1]}`;
  }

  const wickRatioThreshold = value.match(/^Wick ratio (.+) is below the sweep threshold$/u);
  if (wickRatioThreshold) {
    if (locale === "zh") return `影线比例 ${wickRatioThreshold[1]} 低于 sweep 阈值`;
    return `Доля фитиля ${wickRatioThreshold[1]} ниже порога sweep`;
  }

  const priceEma = value.match(/^Price is (above|below) EMA(\d+)$/u);
  if (priceEma) {
    if (locale === "zh") return `价格${translateAboveBelow(priceEma[1] ?? "", locale)} EMA${priceEma[2]}`;
    return `Цена ${translateAboveBelow(priceEma[1] ?? "", locale)} EMA${priceEma[2]}`;
  }

  const emaRelation = value.match(/^(EMA\d+) is (above|below) (EMA\d+)$/u);
  if (emaRelation) {
    if (locale === "zh") return `${emaRelation[1]} ${translateAboveBelow(emaRelation[2] ?? "", locale)} ${emaRelation[3]}`;
    return `${emaRelation[1]} ${translateAboveBelow(emaRelation[2] ?? "", locale)} ${emaRelation[3]}`;
  }

  const adxConfirm = value.match(/^ADX ([\d.]+) confirms trend strength$/u);
  if (adxConfirm) {
    if (locale === "zh") return `ADX ${adxConfirm[1]} 确认趋势强度`;
    return `ADX ${adxConfirm[1]} подтверждает силу тренда`;
  }

  const rsiOutside = value.match(/^RSI ([\d.]+) is outside the healthy pullback zone$/u);
  if (rsiOutside) {
    if (locale === "zh") return `RSI ${rsiOutside[1]} 不在健康回调区间内`;
    return `RSI ${rsiOutside[1]} вне здоровой зоны pullback`;
  }

  const triggerMissing = value.match(/^Trigger is still missing: wait for previous high\/low break with ([\d.]+x) volume$/u);
  if (triggerMissing) {
    if (locale === "zh") return `触发器仍缺失: 等待前高/前低突破并伴随 ${triggerMissing[1]} 成交量`;
    return `Триггера ещё нет: ждём пробой предыдущего high/low с объёмом ${triggerMissing[1]}`;
  }

  const entryLate = value.match(/^Entry is late: distance from EMA(\d+) is above ([\d.]+ ATR)$/u);
  if (entryLate) {
    if (locale === "zh") return `入场偏晚: 距 EMA${entryLate[1]} 超过 ${entryLate[2]}`;
    return `Вход запаздывает: расстояние от EMA${entryLate[1]} больше ${entryLate[2]}`;
  }

  const closeEma = value.match(/^Close (above|below) EMA(\d+)$/u);
  if (closeEma) {
    if (locale === "zh") return `收盘${translateAboveBelow(closeEma[1] ?? "", locale)} EMA${closeEma[2]}`;
    return `Закрытие ${translateAboveBelow(closeEma[1] ?? "", locale)} EMA${closeEma[2]}`;
  }

  const breakSwing = value.match(/^Break (above|below) last swing (high|low)$/u);
  if (breakSwing) {
    const side = breakSwing[2] === "high" ? "high" : "low";
    if (locale === "zh") return `突破最近 swing ${side}`;
    return `Пробой последнего swing ${side}`;
  }

  const rsiReclaims = value.match(/^RSI reclaims the ([\d.]+) zone$/u);
  if (rsiReclaims) {
    if (locale === "zh") return `RSI 重新收复 ${rsiReclaims[1]} 区域`;
    return `RSI возвращает зону ${rsiReclaims[1]}`;
  }

  const regimeAlignmentWithTf = value.match(/^regime alignment: (long|short) vs (bullish|bearish|range|unknown) ([\w]+) \((weak|normal|strong|unknown)\)$/u);
  if (regimeAlignmentWithTf) {
    const side = regimeAlignmentWithTf[1]?.toUpperCase() ?? "";
    const regime = translateMarketEnum(regimeAlignmentWithTf[2] ?? "", locale);
    const timeframe = regimeAlignmentWithTf[3] ?? "";
    const strength = translateMarketEnum(regimeAlignmentWithTf[4] ?? "", locale);
    if (locale === "zh") return `市场状态: ${side} 对 ${timeframe} ${regime} (${strength})`;
    return `Режим: ${side} против ${timeframe} ${regime} (${strength})`;
  }

  const emaChop = value.match(/^ema200 chop: EMA200 chop score ([\d.]+): (\d+) crosses in (\d+) candles, near-ratio ([\d.]+%), slope ([\d.]+ ATR)$/u);
  if (emaChop) {
    if (locale === "zh") return `EMA200 chop: 评分 ${emaChop[1]}, ${emaChop[2]} 次穿越 / ${emaChop[3]} 根K线, 接近比例 ${emaChop[4]}, 斜率 ${emaChop[5]}`;
    return `EMA200 chop: скор ${emaChop[1]}, ${emaChop[2]} пересечений за ${emaChop[3]} свечей, близость ${emaChop[4]}, наклон ${emaChop[5]}`;
  }

  const contextLevel = value.match(/^context (support|resistance): (.+) S\/R (support|resistance) (.+) is (.+ ATR) from entry; strength (\d+), retests (\d+), age (\d+) candles, volume x([\d.]+)$/u);
  if (contextLevel) {
    const levelType = translateSupportResistance(contextLevel[1] ?? "", locale);
    const srType = translateSupportResistance(contextLevel[3] ?? "", locale);
    if (locale === "zh") {
      return `上下文${levelType}: ${contextLevel[2]} S/R ${srType} ${contextLevel[4]} 距入场 ${contextLevel[5]}；强度 ${contextLevel[6]}，回测 ${contextLevel[7]}，年龄 ${contextLevel[8]} 根K线，成交量 x${contextLevel[9]}`;
    }
    return `Контекстная ${levelType}: ${contextLevel[2]} S/R ${srType} ${contextLevel[4]} в ${contextLevel[5]} от входа; сила ${contextLevel[6]}, ретестов ${contextLevel[7]}, возраст ${contextLevel[8]} свечей, объём x${contextLevel[9]}`;
  }

  const regimeAlignmentReason = value.match(/^(long|short) vs (bullish|bearish|range|unknown) ([\w]+) \((weak|normal|strong|unknown)\)$/u);
  if (regimeAlignmentReason) {
    const side = regimeAlignmentReason[1]?.toUpperCase() ?? "";
    const regime = translateMarketEnum(regimeAlignmentReason[2] ?? "", locale);
    const timeframe = regimeAlignmentReason[3] ?? "";
    const strength = translateMarketEnum(regimeAlignmentReason[4] ?? "", locale);
    if (timeframe === "context") {
      if (locale === "zh") return `${side} 对上下文 ${regime} (${strength})`;
      return `${side} против контекста: ${regime} (${strength})`;
    }
    if (locale === "zh") return `${side} 对 ${timeframe} ${regime} (${strength})`;
    return `${side} против ${timeframe} ${regime} (${strength})`;
  }

  const emaChopReason = value.match(/^EMA200 chop score ([\d.]+): (\d+) crosses in (\d+) candles, near-ratio ([\d.]+%), slope ([\d.]+ ATR)$/u);
  if (emaChopReason) {
    if (locale === "zh") return `评分 ${emaChopReason[1]}, ${emaChopReason[2]} 次穿越 / ${emaChopReason[3]} 根K线, 接近比例 ${emaChopReason[4]}, 斜率 ${emaChopReason[5]}`;
    return `скор ${emaChopReason[1]}, ${emaChopReason[2]} пересечений за ${emaChopReason[3]} свечей, близость ${emaChopReason[4]}, наклон ${emaChopReason[5]}`;
  }

  const contextLevelReason = value.match(/^(.+) S\/R (support|resistance) (.+) is (.+ ATR) from entry; strength (\d+), retests (\d+), age (\d+) candles, volume x([\d.]+)$/u);
  if (contextLevelReason) {
    const srType = translateSupportResistance(contextLevelReason[2] ?? "", locale);
    if (locale === "zh") {
      return `${contextLevelReason[1]} S/R ${srType} ${contextLevelReason[3]} 距入场 ${contextLevelReason[4]}；强度 ${contextLevelReason[5]}，回测 ${contextLevelReason[6]}，年龄 ${contextLevelReason[7]} 根K线，成交量 x${contextLevelReason[8]}`;
    }
    return `${contextLevelReason[1]} S/R ${srType} ${contextLevelReason[3]} в ${contextLevelReason[4]} от входа; сила ${contextLevelReason[5]}, ретестов ${contextLevelReason[6]}, возраст ${contextLevelReason[7]} свечей, объём x${contextLevelReason[8]}`;
  }

  if (value === "Expected none context; using signal timeframe only") {
    return locale === "zh"
      ? "未设置上下文，仅使用信号周期"
      : "контекст не задан, используется только TF сигнала";
  }

  const regimeStrengthReason = value.match(/^Higher timeframe trend strength is (weak|normal|strong|unknown)$/u);
  if (regimeStrengthReason) {
    const strength = translateMarketEnum(regimeStrengthReason[1] ?? "", locale);
    if (locale === "zh") return `高周期趋势强度为 ${strength}`;
    return `тренд старшего TF ${strength}`;
  }

  const donchianWait = value.match(/^Volatility is compressed and price is near the (upper|lower) Donchian boundary; waiting for breakout volume and a candle close outside the range$/u);
  if (donchianWait) {
    const boundary = donchianWait[1] === "upper"
      ? locale === "zh" ? "上" : "верхней"
      : locale === "zh" ? "下" : "нижней";
    if (locale === "zh") return `波动率被压缩，价格接近 Donchian ${boundary}边界；等待突破成交量和区间外收盘`;
    return `Волатильность сжата, цена рядом с ${boundary} границей Donchian; ждём breakout-объём и закрытие свечи вне диапазона`;
  }

  const bbWidth = value.match(/^BB width percentile is compressed below ([\d.]+)$/u);
  if (bbWidth) {
    if (locale === "zh") return `BB 宽度百分位压缩到 ${bbWidth[1]} 以下`;
    return `Перцентиль ширины BB сжат ниже ${bbWidth[1]}`;
  }

  const measuredMove = value.match(/^Measured move target: (.+)$/u);
  if (measuredMove) {
    if (locale === "zh") return `量度目标: ${measuredMove[1]}`;
    return `Цель measured move: ${measuredMove[1]}`;
  }

  const squeezeRange = value.match(/^Squeeze range uses ([\d.]+ ATR); wider ranges are less clean$/u);
  if (squeezeRange) {
    if (locale === "zh") return `Squeeze 区间占用 ${squeezeRange[1]}；更宽的区间不够干净`;
    return `Squeeze-диапазон занимает ${squeezeRange[1]}; более широкие диапазоны менее чистые`;
  }

  const closeDonchian = value.match(/^Close finished outside the Donchian (range high|range low)$/u);
  if (closeDonchian) {
    const level = closeDonchian[1] === "range high" ? "range high" : "range low";
    if (locale === "zh") return `收盘在 Donchian ${level} 之外`;
    return `Закрытие вышло за Donchian ${level}`;
  }

  const breakoutVolume = value.match(/^Breakout volume is ([\d.]+x) average$/u);
  if (breakoutVolume) {
    if (locale === "zh") return `Breakout 成交量为平均值的 ${breakoutVolume[1]}`;
    return `Breakout-объём ${breakoutVolume[1]} от среднего`;
  }

  const strongClose = value.match(/^Close is in the directional part of the candle: (.+)$/u);
  if (strongClose) {
    if (locale === "zh") return `收盘位于K线方向性区域: ${strongClose[1]}`;
    return `Закрытие в направленной части свечи: ${strongClose[1]}`;
  }

  const breakoutBody = value.match(/^Breakout candle body is ([\d.]+ ATR)$/u);
  if (breakoutBody) {
    if (locale === "zh") return `Breakout K线实体为 ${breakoutBody[1]}`;
    return `Тело breakout-свечи ${breakoutBody[1]}`;
  }

  const rejectionWickRange = value.match(/^Rejection wick is (.+) of the candle range$/u);
  if (rejectionWickRange) {
    if (locale === "zh") return `拒绝影线占K线区间的 ${rejectionWickRange[1]}`;
    return `Rejection-фитиль занимает ${rejectionWickRange[1]} диапазона свечи`;
  }

  const rsiMomentum = value.match(/^RSI ([\d.]+) supports (upside|downside) momentum without extreme heat$/u);
  if (rsiMomentum) {
    const direction = rsiMomentum[2] === "upside"
      ? locale === "zh" ? "上行" : "вверх"
      : locale === "zh" ? "下行" : "вниз";
    if (locale === "zh") return `RSI ${rsiMomentum[1]} 支持${direction}动能，且没有极端过热`;
    return `RSI ${rsiMomentum[1]} поддерживает импульс ${direction} без экстремального перегрева`;
  }

  const enumLike = translateEnumLike(value, locale);
  if (enumLike !== value) return enumLike;

  return value;
}

const tradeTextMap: Record<string, Partial<Record<Locale, string>>> = {
  "ATR value is unavailable; using trailing percent fallback.": {
    ru: "ATR недоступен; используем резервный процентный трейлинг.",
    zh: "ATR 不可用；使用追踪百分比回退。"
  },
  "ADX/context is not a strong local trend against the reversal": {
    ru: "ADX/контекст не показывает сильный локальный тренд против разворота",
    zh: "ADX/上下文未显示反转方向上的强局部趋势"
  },
  "Close settled beyond the swept level; this may be a real breakout": {
    ru: "Закрытие закрепилось за снятым уровнем; это может быть настоящий breakout",
    zh: "收盘站上被扫水平之外；这可能是真突破"
  },
  "Close returns below swept low": {
    ru: "Закрытие возвращается ниже снятого low",
    zh: "收盘回到被扫低点下方"
  },
  "Level has equal-high/low style retests": {
    ru: "У уровня есть ретесты в стиле equal-high/low",
    zh: "该水平有 equal-high/low 类型的回测"
  },
  "Next candles fail to hold reclaim": {
    ru: "Следующие свечи не удерживают reclaim",
    zh: "后续K线未能守住重新收复位"
  },
  "Position notional is below exchange minimum notional.": {
    ru: "Номинал позиции ниже минимального значения биржи.",
    zh: "仓位名义价值低于交易所最小名义金额。"
  },
  "Position size is below exchange minimum order size.": {
    ru: "Размер позиции ниже минимального размера ордера на бирже.",
    zh: "仓位规模低于交易所最小下单量。"
  },
  "Price has not pulled back into the EMA20/EMA50 zone yet": {
    ru: "Цена ещё не откатилась в зону EMA20/EMA50",
    zh: "价格尚未回调到 EMA20/EMA50 区域"
  },
  "Price is chopping around EMA200; trend-continuation setups are less reliable": {
    ru: "Цена пилит вокруг EMA200; trend-continuation setup менее надёжен",
    zh: "价格围绕 EMA200 震荡；趋势延续 setup 可靠性较低"
  },
  "Price swept visible liquidity": {
    ru: "Цена сняла видимую ликвидность",
    zh: "价格扫过可见流动性"
  },
  "Pullback volume is at or below average": {
    ru: "Объём на pullback на уровне среднего или ниже",
    zh: "回调成交量等于或低于平均值"
  },
  "Signal is too close to higher-timeframe support/resistance": {
    ru: "Сигнал слишком близко к поддержке/сопротивлению старшего TF",
    zh: "信号离高周期支撑/阻力太近"
  },
  "Signal is against a strong higher-timeframe regime": {
    ru: "Сигнал против сильного режима старшего TF",
    zh: "信号逆着强高周期状态"
  },
  "Signal score is below the minimum tradable threshold.": {
    ru: "Скор сигнала ниже минимального торгового порога.",
    zh: "信号评分低于最小可交易阈值。"
  },
  "Strategy setup exists, but confirmation is incomplete": {
    ru: "Setup стратегии есть, но подтверждение неполное",
    zh: "策略 setup 已形成，但确认尚未完成"
  },
  "Sweep candle also broke micro structure toward reversal": {
    ru: "Sweep-свеча также пробила микроструктуру в сторону разворота",
    zh: "扫单K线也朝反转方向突破了微结构"
  },
  "Sweep has not reclaimed the level yet": {
    ru: "Sweep ещё не вернул уровень",
    zh: "扫单尚未重新收复该水平"
  },
  "Sweep lacks strong volume confirmation": {
    ru: "Sweep без сильного подтверждения объёмом",
    zh: "扫单缺少强成交量确认"
  },
  "Sweep low is broken again": {
    ru: "Sweep low снова пробит",
    zh: "扫低点再次被跌破"
  },
  "Swept level was reclaimed with a strong wick, close and volume": {
    ru: "Снятый уровень вернули сильным фитилем, закрытием и объёмом",
    zh: "被扫水平通过强影线、收盘和成交量重新收复"
  },
  "Swept level was reclaimed; waiting for stronger wick, volume or confirmation candle": {
    ru: "Снятый уровень вернули; ждём более сильный фитиль, объём или подтверждающую свечу",
    zh: "被扫水平已收复；等待更强影线、成交量或确认K线"
  },
  "Volume disappears after reclaim": {
    ru: "Объём исчезает после reclaim",
    zh: "重新收复后成交量消失"
  },
  "20-candle range is below its recent average": {
    ru: "Диапазон 20 свечей ниже своего недавнего среднего",
    zh: "20 根K线区间低于近期均值"
  },
  "ATR has not started expanding yet": {
    ru: "ATR ещё не начал расширяться",
    zh: "ATR 尚未开始扩张"
  },
  "ATR is below its 50-candle average": {
    ru: "ATR ниже среднего за 50 свечей",
    zh: "ATR 低于 50 根K线均值"
  },
  "ATR is expanding after compression": {
    ru: "ATR расширяется после сжатия",
    zh: "ATR 在压缩后开始扩张"
  },
  "Breakdown candle is fully retraced": {
    ru: "Breakdown-свеча полностью отретрейсилась",
    zh: "Breakdown K线被完全回撤"
  },
  "Breakout volume is below the configured confirmation multiplier": {
    ru: "Breakout-объём ниже заданного множителя подтверждения",
    zh: "Breakout 成交量低于配置的确认倍数"
  },
  "Close is not strong enough inside the breakout candle": {
    ru: "Закрытие недостаточно сильное внутри breakout-свечи",
    zh: "Breakout K线内的收盘不够强"
  },
  "Close returns inside the previous Donchian range": {
    ru: "Закрытие возвращается внутрь предыдущего диапазона Donchian",
    zh: "收盘回到前一个 Donchian 区间内"
  },
  "Price is pressing the Donchian boundary before confirmation": {
    ru: "Цена давит на границу Donchian до подтверждения",
    zh: "确认前价格压向 Donchian 边界"
  },
  "Price pierced the range but closed back inside": {
    ru: "Цена проколола диапазон, но закрылась обратно внутри",
    zh: "价格刺穿区间但收回内部"
  },
  "RSI above 75: late long breakout risk": {
    ru: "RSI выше 75: риск позднего LONG breakout",
    zh: "RSI 高于 75：LONG breakout 偏晚风险"
  },
  "RSI below 25: late short breakdown risk": {
    ru: "RSI ниже 25: риск позднего SHORT breakdown",
    zh: "RSI 低于 25：SHORT breakdown 偏晚风险"
  },
  "Volume disappears after breakdown": {
    ru: "Объём исчезает после breakdown",
    zh: "Breakdown 后成交量消失"
  }
};

function translateLiquidityDepth(value: string, locale: Locale): string {
  if (value === "current depth") return locale === "zh" ? "当前深度" : "текущую глубину";
  const match = value.match(/^(.+) of liquidity inside 1%$/u);
  if (!match) return value;
  return locale === "zh" ? `1% 内流动性的 ${match[1]}` : `${match[1]} ликвидности внутри 1%`;
}

function translateAboveBelow(value: string, locale: Locale): string {
  if (value === "above") return locale === "zh" ? "高于" : "выше";
  if (value === "below") return locale === "zh" ? "低于" : "ниже";
  return value;
}

function translateSupportResistance(value: string, locale: Locale): string {
  if (value === "support") return locale === "zh" ? "支撑" : "поддержка";
  if (value === "resistance") return locale === "zh" ? "阻力" : "сопротивление";
  return value;
}

function translateEnumLike(value: string, locale: Locale): string {
  const targets = value.match(/^(\d+) targets$/iu);
  if (targets) return locale === "zh" ? `${targets[1]} 个目标` : `${targets[1]} цели`;

  if (!/[A-Za-z]/.test(value)) return value;
  const separators = value.includes(" / ") ? " / " : value.includes(" vs ") ? " vs " : null;
  if (!separators) return value;

  const parts = value.split(separators);
  const translatedParts = parts.map((part) => translateMarketEnum(part, locale));
  if (translatedParts.every((part, index) => part === parts[index])) return value;
  return translatedParts.join(separators);
}

function translateMarketEnum(value: string, locale: Locale): string {
  const normalized = value.trim().toLowerCase().replaceAll("_", " ");
  const map: Record<string, Partial<Record<Locale, string>>> = {
    against: { ru: "против", zh: "逆向" },
    aligned: { ru: "по тренду", zh: "同向" },
    bearish: { ru: "медвежий", zh: "看跌" },
    bullish: { ru: "бычий", zh: "看涨" },
    confirmed: { ru: "подтверждён", zh: "已确认" },
    forming: { ru: "формируется", zh: "形成中" },
    major: { ru: "мажор", zh: "主流" },
    "mid alt": { ru: "средний альт", zh: "中型山寨" },
    mixed: { ru: "смешанный", zh: "混合" },
    normal: { ru: "нормальный", zh: "正常" },
    pending: { ru: "ожидание", zh: "等待" },
    range: { ru: "боковик", zh: "震荡" },
    ready: { ru: "готов", zh: "就绪" },
    strong: { ru: "сильный", zh: "强" },
    unknown: { ru: "неизвестно", zh: "未知" },
    weak: { ru: "слабый", zh: "弱" }
  };
  return map[normalized]?.[locale] ?? value;
}

function translateAge(value: string, locale: Locale): string {
  if (locale === "en") return value;
  if (value === "waiting for data") return locale === "zh" ? "等待数据" : "ожидаем данные";
  if (value === "just now") return locale === "zh" ? "刚刚" : "только что";

  const unitMatch = value.match(/^(\d+)(ms|s|m|h)(?: ago)?$/u);
  if (!unitMatch) return value;

  const amount = unitMatch[1];
  const unit = unitMatch[2];
  if (locale === "zh") {
    const unitText = unit === "ms" ? "毫秒前" : unit === "s" ? "秒前" : unit === "m" ? "分钟前" : "小时前";
    return `${amount}${unitText}`;
  }
  const unitText = unit === "ms" ? "мс назад" : unit === "s" ? "с назад" : unit === "m" ? "м назад" : "ч назад";
  return `${amount}${unitText}`;
}

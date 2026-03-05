# 💪 My Fitness Bot

Персональный Telegram-бот для управления тренировками. Создавай программы, планируй фазы, получай напоминания прямо в мессенджере.

---

## 🇷🇺 Русский

### Что умеет

- 📋 Создавать тренировочные программы с несколькими фазами
- 🗓️ Назначать дни недели и время для каждой фазы
- 🏋️ Хранить упражнения и группы мышц по дням
- 🔔 Отправлять напоминания о тренировке по расписанию
- ✏️ Редактировать и удалять программы

### Быстрый старт

**Локально:**

```bash
# 1. Клонируй репозиторий
git clone <repo-url>
cd my_fitness_bot_v2.0

# 2. Установи зависимости
pip install -r requirements.txt

# 3. Заполни .env
BOT_TOKEN=твой_токен_от_BotFather
DEVELOPER_ID=твой_telegram_id

# 4. Запусти
python tg_bot.py
```

**Docker:**

```bash
# Заполни .env, затем:
docker-compose up -d --build

# Логи
docker-compose logs -f

# Остановить
docker-compose down
```

### Структура

```
my_fitness_bot_v2.0/
├── tg_bot.py            # основной бот
├── data.json            # данные пользователей
├── .env                 # токен и ID (не публикуй!)
├── docker-compose.yml
├── Dockerfile
└── logs/                # логи бота
```

### Получить токен

1. Открой [@BotFather](https://t.me/BotFather) в Telegram
2. Создай бота командой `/newbot`
3. Скопируй токен в `.env`

Узнать свой Telegram ID → [@userinfobot](https://t.me/userinfobot)

---

## 🇬🇧 English

### Features

- 📋 Create workout programs with multiple phases
- 🗓️ Set days of the week and time for each phase
- 🏋️ Store exercises and muscle groups per day
- 🔔 Get scheduled workout reminders
- ✏️ Edit and delete programs

### Quick Start

**Local:**

```bash
# 1. Clone the repo
git clone <repo-url>
cd my_fitness_bot_v2.0

# 2. Install dependencies
pip install -r requirements.txt

# 3. Fill in .env
BOT_TOKEN=your_token_from_BotFather
DEVELOPER_ID=your_telegram_id

# 4. Run
python tg_bot.py
```

**Docker:**

```bash
# Fill in .env, then:
docker-compose up -d --build

# Logs
docker-compose logs -f

# Stop
docker-compose down
```

### Project Structure

```
my_fitness_bot_v2.0/
├── tg_bot.py            # main bot
├── data.json            # user data storage
├── .env                 # token & ID (keep private!)
├── docker-compose.yml
├── Dockerfile
└── logs/                # bot logs
```

### Get a Token

1. Open [@BotFather](https://t.me/BotFather) in Telegram
2. Create a bot with `/newbot`
3. Copy the token into `.env`

Find your Telegram ID → [@userinfobot](https://t.me/userinfobot)

---

> ⚠️ Никогда не публикуй `.env` с реальными данными / Never commit `.env` with real credentials

#!/usr/bin/env bash
# Настройка бота: проверяет токен, определяет ваш telegram-id и пишет .env.
#
# Токен вводится скрыто и никуда, кроме .env, не попадает: ни в историю
# командной строки, ни в вывод, ни в логи.
set -euo pipefail

cd "$(dirname "$0")"
API="https://api.telegram.org/bot"

for tool in curl python3; do
  command -v "$tool" >/dev/null || { echo "нужен $tool"; exit 1; }
done

json() { python3 -c "import json,sys; d=json.load(sys.stdin); print(eval(sys.argv[1],{'d':d}) if d.get('ok') else '')" "$1" 2>/dev/null || true; }

if [ -f .env ]; then
  read -rp ".env уже есть. Перезаписать? [y/N] " ans
  [[ "${ans,,}" == "y" ]] || { echo "Оставил как было."; exit 0; }
fi

echo
echo "1. Открой @BotFather в телеграме, отправь /newbot и следуй подсказкам."
echo "   Имя — любое, юзернейм должен заканчиваться на «bot»."
echo "   В конце BotFather пришлёт строку вида 8123456789:AAF..."
echo
read -rsp "2. Вставь токен (ввод скрыт) и нажми Enter: " TOKEN
echo
[ -n "$TOKEN" ] || { echo "Пустой токен."; exit 1; }

echo -n "   Проверяю… "
ME=$(curl -sS --max-time 20 "${API}${TOKEN}/getMe")
USERNAME=$(printf '%s' "$ME" | json "d['result']['username']")
if [ -z "$USERNAME" ]; then
  echo "токен не принят."
  echo "   Скопируй строку целиком, вместе с цифрами до двоеточия."
  exit 1
fi
echo "это @${USERNAME}."

echo
echo "3. Открой https://t.me/${USERNAME} и нажми «Начать» (Start)."
read -rp "   Нажал? Enter — определю твой id: "

ADMIN=""
for _ in 1 2 3 4 5 6; do
  UPD=$(curl -sS --max-time 20 "${API}${TOKEN}/getUpdates?limit=10")
  ADMIN=$(printf '%s' "$UPD" | json "d['result'][-1]['message']['from']['id']")
  WHO=$(printf '%s' "$UPD" | json "d['result'][-1]['message']['from'].get('username','')")
  [ -n "$ADMIN" ] && break
  sleep 2
done

if [ -z "$ADMIN" ]; then
  echo "   Не увидел сообщения. Ничего страшного — узнай свой id у @userinfobot."
  read -rp "   Введи его вручную: " ADMIN
else
  echo "   Нашёл: ${ADMIN}${WHO:+ (@$WHO)}"
fi

read -rp "4. Чей телеграм показывать как поддержку, без собаки: " SUPPORT
[ -n "$SUPPORT" ] || { echo "Без этого кнопка «написать преподавателю» вести некуда."; exit 1; }

umask 077
cat > .env <<ENVEOF
BOT_TOKEN=${TOKEN}
ADMIN_IDS=${ADMIN}
SUPPORT_USERNAME=${SUPPORT}
DATA_ROOT=/data
DB_PATH=/state/mlbot.sqlite3
# Предохранитель: пока он включён, сообщения посторонним не уходят.
# Снимать осознанно и отдельно — см. README.
SAFE_MODE=1
ENVEOF
chmod 600 .env
unset TOKEN

echo
echo "Готово. .env создан с правами 600 — в git он не попадёт."
echo
echo "Запуск на сервере:   docker compose up -d --build"
echo "Запуск локально:     DATA_ROOT=.. uv run --env-file .env mlbot"
echo
echo "Дальше в самом боте: /start → появится кнопка «🛠 Админка»."

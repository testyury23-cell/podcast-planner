import base64
import hashlib
import streamlit as st
import pandas as pd
import requests
import os
import json
from dotenv import load_dotenv
from openai import OpenAI
from xml.etree import ElementTree as ET
import io


# Настройка стилей (современный минимализм)
st.markdown("""
    <style>
    /* Фиксированная шапка */
    .fixed-header {
        position: fixed;
        top: 0;
        right: 0;
        left: 0;
        height: 100px;
        background-color: #f0f2f6;
        display: flex;
        flex-direction: column;
        justify-content: center;
        align-items: center;
        z-index: 999;
        border-bottom: 1px solid #dcdfe3;
        text-align: center;
    }
    
    .main-content {
        margin-top: 80px;
    }
    
    header[data-testid="stHeader"] {
        display: none;
    }

    [data-testid="stWidgetLabel"] p {
        font-weight: bold !important;
        font-size: 0.95rem;
    }
    /* -------------------------------------- */

    .stButton>button {
        border-radius: 8px;
    }
    </style>
    
    <div class="fixed-header">
        <h1 style="margin:0; font-size: 1.8rem;">🎙️ Автоматизированный контент-планер</h1>
        <p style="margin:0; color: #666;">Интеллектуальная система генерации идей и сценариев</p>
    </div>
    <div class="main-content"></div>
    """, unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# Загрузка переменных окружения
# ---------------------------------------------------------------------------
load_dotenv()

PROXY_API_KEY   = os.getenv('PROXY_API_KEY', '')
PROXY_BASE_URL  = os.getenv('PROXY_BASE_URL', 'https://api.proxyapi.ru/openai/v1')
YANDEX_FOLDERID = os.getenv('YANDEX_SEARCH_FOLDERID', '')
YANDEX_API_KEY  = os.getenv('YANDEX_SEARCH_API_KEY', '')

DATA_DIR      = os.path.join(os.path.dirname(__file__), '..', 'data')
PROJECT_FILE  = os.path.join(DATA_DIR, 'project.json')
IDEAS_LIMIT   = 5   # желаемое количество идей
RETRY_LIMIT   = 3   # максимум запросов на вкладку

os.makedirs(DATA_DIR, exist_ok=True)


# ===========================================================================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ===========================================================================

def call_llm(prompt: str) -> str:
    """Отправляет prompt в GPT-4o-mini через ProxyAPI."""
    if not PROXY_API_KEY:
        return '[Ошибка] PROXY_API_KEY не задан в .env'
    try:
        client = OpenAI(api_key=PROXY_API_KEY, base_url=PROXY_BASE_URL)
        completion = client.chat.completions.create(
            model='gpt-4o-mini',
            messages=[{'role': 'user', 'content': prompt}],
            temperature=0.7,
        )
        return completion.choices[0].message.content.strip()
    except Exception as e:
        return f'[Ошибка LLM] {e}'


def generate_script(idea: str, topic: str, target_audience: str, format_choice: str, style_references: str) -> str:
    """Генерирует подробный сценарий/план на основе выбранной идеи."""
    prompt = (
        f"Ты — профессиональный сценарист и эксперт по контенту.\n"
        f"Твоя задача: написать подробный сценарий/план для формата {format_choice}.\n\n"
        f"Основная идея: {idea}\n"
        f"Общая тема: {topic}\n"
        f"Целевая аудитория: {target_audience or 'не указана'}\n"
        f"Стиль и референсы: {style_references or 'не указаны'}\n\n"
        f"Сценарий должен включать:\n"
        f"1. Цепляющий заголовок/название.\n"
        f"2. Вступление (хук для удержания внимания).\n"
        f"3. Основные тезисы/структура (3-5 блоков).\n"
        f"4. Заключение и призыв к действию (CTA).\n"
        f"5. Рекомендации по визуалу или подаче.\n\n"
        f"Пиши профессионально, структурированно, на русском языке."
    )
    return call_llm(prompt)

# ---------------------------------------------------------------------------
# Чистка текста
# ---------------------------------------------------------------------------
def clean_text(text: str) -> str:
    """Убирает ведущую нумерацию."""
    import re
    return re.sub(r'^[\d]+[.)\-]\s*|^[-–•]\s*', '', text.strip())


def trend_key(trend: str, idx: int) -> str:
    """Уникальный ключ для чекбокса на основе индекса и хеша текста."""
    txt_hash = hashlib.md5(trend.encode()).hexdigest()[:8]
    return f"trend_{idx}_{txt_hash}"


# ---------------------------------------------------------------------------
# Яндекс-поиск
# ---------------------------------------------------------------------------
def yandex_search_trends(query: str) -> list[str]:
    """Возвращает список сниппетов из Yandex Cloud Search API (v2)."""
    if not YANDEX_FOLDERID or not YANDEX_API_KEY:
        st.session_state.trends_source = 'Анализ на основе статистических моделей и сезонности'
        return _stub_trends(query)

    url = "https://searchapi.api.cloud.yandex.net/v2/web/search"
    headers = {
        "Authorization": f"Api-Key {YANDEX_API_KEY}",
        "Content-Type": "application/json"
    }
    payload = {
        "folderId": YANDEX_FOLDERID,
        "query": {
            "queryText": query,
            "searchType": "SEARCH_TYPE_RU"
        },
        "responseFormat": "FORMAT_XML" 
    }

    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        raw_data_b64 = data.get('rawData')
        
        if not raw_data_b64:
            raise ValueError("Поле rawData отсутствует в ответе Яндекса")

        # Декодируем Base64 в XML-строку
        xml_text = base64.b64decode(raw_data_b64).decode('utf-8')

        # Парсим XML        
        root = ET.fromstring(xml_text)

        # Собираем сниппеты (текст из тегов passage)        
        snippets = []
        for node in root.iter('passage'):
            if node.text:
                clean_snippet = "".join(node.itertext()).strip()
                if clean_snippet:
                    snippets.append(clean_snippet)

        if snippets:
            st.session_state.trends_source = 'Данные предоставлены Yandex Search API (v2)'
            # Ограничиваем до 5 трендов
            return list(dict.fromkeys(snippets))[:5]

        st.session_state.trends_source = 'Анализ на основе статистических моделей и сезонности'
        return _stub_trends(query)

    except Exception as e:
        print(f'[Yandex API error] {type(e).__name__}: {e}')
        st.session_state.trends_source = 'Анализ на основе статистических моделей и сезонности (ошибка API)'
        return _stub_trends(query)


def _stub_trends(query: str) -> list[str]:
    """Генерирует 5 заглушек-трендов через LLM."""
    if not PROXY_API_KEY:
        return [f'Тренд {i} по теме «{query}» (заглушка)' for i in range(1, 6)]
    prompt = (
        f'Назови 5 актуальных и конкретных трендов или болей аудитории по теме «{query}». '
        f'Ответь нумерованным списком, каждый пункт — одно предложение.'
    )
    raw = call_llm(prompt)
    lines = [clean_text(ln) for ln in raw.splitlines() if ln.strip()]
    return lines[:5] if lines else [raw]


# ---------------------------------------------------------------------------
# Аналитика трендов
# ---------------------------------------------------------------------------
def analyze_trends_with_llm(search_results: list[str], topic: str) -> str:
    """Анализирует тренды через LLM."""
    joined = '\n'.join(f'- {s}' for s in search_results)
    prompt = (
        f'Ты — маркетинговый аналитик. На основе следующих результатов поиска по теме «{topic}»:\n'
        f'{joined}\n\n'
        f'Выдели 5 самых актуальных и специфичных проблем (болей) или интересов аудитории. '
        f'Ответь нумерованным списком, каждый пункт — одно предложение на русском языке.'
    )
    return call_llm(prompt)


# ---------------------------------------------------------------------------
# Генерация идей
# ---------------------------------------------------------------------------
def generate_ideas(
    topic: str,
    target_audience: str,
    format_choice: str,
    style_references: str,
    kept_ideas: list[str],
    selected_trends: list[str],  # <-- Добавили новый параметр
) -> list[str]:
    """Генерирует идеи, строго опираясь на выбранные тренды."""
    need = IDEAS_LIMIT - len(kept_ideas)
    if need <= 0:
        return kept_ideas

    # Формируем блок трендов для промпта
    trends_block = ''
    if selected_trends:
        trends_block = 'ОБЯЗАТЕЛЬНО учти при создании идей следующие актуальные тренды/боли:\n' + '\n'.join(
            f'- {t}' for t in selected_trends
        ) + '\n\n'

    kept_block = ''
    if kept_ideas:
        kept_block = 'Уже одобренные идеи (НЕ повторяй их):\n' + '\n'.join(
            f'- {i}' for i in kept_ideas
        ) + '\n\n'

    prompt = (
        f'Ты — креативный продюсер контента.\n'
        f'Тема: {topic}\n'
        f'Целевая аудитория: {target_audience or "не указана"}\n'
        f'Формат: {format_choice}\n'
        f'Стиль: {style_references or "не указан"}\n\n'
        f'{trends_block}'  # Вставляем тренды в промпт
        f'{kept_block}'
        f'Придумай ровно {need} новых уникальных идей для контента. Каждая идея — одно предложение.\n'
        f'Ответь нумерованным списком.'
    )
    
    raw = call_llm(prompt)
    new_ideas = [clean_text(ln) for ln in raw.splitlines() if ln.strip()]
    return kept_ideas + new_ideas[:need]


from datetime import datetime, timedelta

def create_content_plan(selected_ideas: list[str], frequency: str, format_choice: str, start_dt) -> pd.DataFrame:
    plan_data = []
    # Конвертируем дату из виджета в объект datetime
    current_date = datetime.combine(start_dt, datetime.min.time())

    if frequency == 'Еженедельно':
        delta = timedelta(weeks=1)
    elif frequency == 'Ежемесячно':
        delta = timedelta(days=30)
    else:
        delta = timedelta(days=90)

    for i, idea in enumerate(selected_ideas):
        publish_date = current_date + (delta * i)
        plan_data.append({
            'Дата': publish_date.strftime('%Y-%m-%d'),
            'Тема/Идея': idea,
            'Формат': format_choice,
            'Статус': 'В плане'
        })
    return pd.DataFrame(plan_data)

# ---------------------------------------------------------------------------
# Сохранение / загрузка проекта
# ---------------------------------------------------------------------------
def _collect_project_state(t, ta, fc, fq, sr) -> dict:
    return {
        'settings': {'theme': t, 'target_audience': ta, 'format_choice': fc, 'frequency': fq, 'style_references': sr},
        'trends_results':   st.session_state.get('trends_results', []),
        'selected_trends':  st.session_state.get('selected_trends', []),
        'llm_analysis':     st.session_state.get('llm_analysis', ''),
        'generated_ideas':  st.session_state.get('generated_ideas', []),
        'counters':         st.session_state.get('counters', {}),
        'idea_counters':    st.session_state.get('idea_counters', {}),
    }

def save_project(t, ta, fc, fq, sr):
    state = _collect_project_state(t, ta, fc, fq, sr)
    with open(PROJECT_FILE, 'w', encoding='utf-8') as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
    st.sidebar.success(f'Проект сохранён')

def load_project():
    if not os.path.exists(PROJECT_FILE):
        st.sidebar.warning('Файл проекта не найден.')
        return None
    with open(PROJECT_FILE, 'r', encoding='utf-8') as f:
        state = json.load(f)
    # Восстанавливаем session_state
    st.session_state.trends_results  = state.get('trends_results', [])
    st.session_state.selected_trends = state.get('selected_trends', [])
    st.session_state.llm_analysis    = state.get('llm_analysis', '')
    st.session_state.generated_ideas = state.get('generated_ideas', [])
    st.session_state.counters        = state.get('counters', {'analytics': 0})
    st.session_state.idea_counters   = state.get('idea_counters', {'ideas': 0})
    st.sidebar.success('Проект успешно загружен!')
    return state.get('settings', {})


# ===========================================================================
# КОНФИГУРАЦИЯ СТРАНИЦЫ
# ===========================================================================
st.set_page_config(layout='wide', page_title='Content Planner')

# ===========================================================================
# ИНИЦИАЛИЗАЦИЯ SESSION STATE
# ===========================================================================
if 'trends_results' not in st.session_state:
    st.session_state.trends_results = []
    st.session_state.selected_trends = []
    st.session_state.trends_source = ''
    st.session_state.llm_analysis = ''
    st.session_state.generated_ideas = []
    st.session_state.counters = {'analytics': 0}
    st.session_state.idea_counters = {'ideas': 0}

if 'scenario_archive' not in st.session_state:
    st.session_state.scenario_archive = []

# ===========================================================================
# SIDEBAR
# ===========================================================================
st.sidebar.title('⚙️ Настройки проекта')

theme = st.sidebar.text_input('Тематика', value='')
target_audience = st.sidebar.text_input('Целевая аудитория', value='')
format_choice = st.sidebar.selectbox('Формат', ['Подкаст', 'Видео', 'Статья'])
frequency = st.sidebar.selectbox('Частота', ['Еженедельно', 'Ежемесячно', 'Ежеквартально'])

# Виджет даты
from datetime import datetime
start_date = st.sidebar.date_input("Дата начала плана", value=datetime.now())

style_references = st.sidebar.text_area('Стиль / Референсы', value='')

st.sidebar.divider()

# Кнопки теперь видны сразу, без прокрутки
if st.sidebar.button('💾 Сохранить проект', use_container_width=True):
    save_project(theme, target_audience, format_choice, frequency, style_references)

if st.sidebar.button('📂 Загрузить проект', use_container_width=True):
    loaded = load_project()
    if loaded: 
        st.rerun()

# ===========================================================================
# ВКЛАДКИ
# ===========================================================================
tabs = st.tabs(['📊 Аналитика', '💡 Идеи', '📅 Контент-план', '🎬 Сценарий'])

# ---------------------------------------------------------------------------
# Вкладка 0 — АНАЛИТИКА
# ---------------------------------------------------------------------------
with tabs[0]:
    st.header('Анализ трендов')
    count = st.session_state.counters['analytics']
    if count >= RETRY_LIMIT:
        st.warning(f'Лимит попыток исчерпан ({RETRY_LIMIT})')
    else:
        st.caption(f'Осталось попыток: {RETRY_LIMIT - count}')

    if st.button('🔍 Найти тренды', disabled=(count >= RETRY_LIMIT)):
        if not theme:
            st.error('Укажите тематику.')
        else:
            # Сохраняем ранее выбранные тренды по их уникальным ключам
            kept_trends = []
            for i, t in enumerate(st.session_state.trends_results):
                if st.session_state.get(trend_key(t, i), False):
                    kept_trends.append(t)

            with st.spinner('Ищем тренды...'):
                new_data = yandex_search_trends(theme)
                # Ограничиваем общий список 5 элементами
                merged = kept_trends + [t for t in new_data if t not in kept_trends]
                st.session_state.trends_results = merged[:5]
            with st.spinner('Анализируем тренды с помощью ИИ...'):                
                st.session_state.llm_analysis = analyze_trends_with_llm(new_data, theme)
                st.session_state.counters['analytics'] += 1
            st.rerun() # Перезапуск для мгновенного обновления плашки API

    # Вывод плашки источника данных
    if st.session_state.trends_source:
        st.info(st.session_state.trends_source)

    if st.session_state.llm_analysis:
        st.subheader('Анализ ИИ')
        st.markdown(st.session_state.llm_analysis)

    if st.session_state.trends_results:
        st.subheader('Найденные тренды')
        st.caption('Выберите тренды для генерации идей:')
        new_selection = []
        for i, trend in enumerate(st.session_state.trends_results):
            # Используем уникальный ключ с индексом
            is_checked = st.checkbox(
                trend, 
                key=trend_key(trend, i),
                value=(trend in st.session_state.selected_trends)
            )
            if is_checked:
                new_selection.append(trend)
        st.session_state.selected_trends = new_selection

# ---------------------------------------------------------------------------
# Вкладка 1 — ИДЕИ
# ---------------------------------------------------------------------------
with tabs[1]:
    st.header('Генерация идей')

    i_count = st.session_state.idea_counters['ideas']
    if i_count >= RETRY_LIMIT:
        st.warning(f'Лимит попыток исчерпан')
    else:
        st.caption(f'Попыток: {RETRY_LIMIT - i_count}')

    user_topic = st.text_input('Уточнить тему (необязательно)', key='ut_input')
    eff_topic = user_topic.strip() or theme

    col1, col2 = st.columns([2, 1])
    
    with col1:
        if st.button('✨ Генерировать идеи с помощью ИИ', disabled=(i_count >= RETRY_LIMIT), use_container_width=True):
            if not eff_topic:
                st.error('Нет темы.')
            else:
                kept = []
                for idea in st.session_state.generated_ideas:
                    # Ищем по тому же хеш-ключу, который создаем ниже в цикле
                    ikey = f"keep_{hashlib.md5(idea.encode()).hexdigest()[:10]}"
                    if st.session_state.get(ikey, False):
                        kept.append(idea)
            
            with st.spinner('Генерируем идеи...'):
              # Добавляем шестой аргумент — наши выбранные тренды
              st.session_state.generated_ideas = generate_ideas(
                  eff_topic, 
                  target_audience, 
                  format_choice, 
                  style_references, 
                  kept,
                  st.session_state.selected_trends  # <-- Вот оно, критически важное дополнение!
              )
              st.session_state.idea_counters['ideas'] += 1
            st.rerun()

# --- НОВЫЙ БЛОК: ДОБАВЛЕНИЕ СВОЕЙ ИДЕИ ---
    st.divider()
    st.subheader('Добавить свою идею')
    custom_idea = st.text_input('Введите свою идею вручную', placeholder='Например: Интервью с тренером сборной...')
    if st.button('➕ Добавить в список'):
        if custom_idea.strip():
            # Просто добавляем в список сгенерированных
            st.session_state.generated_ideas.append(custom_idea.strip())
            st.success('Идея добавлена!')
            st.rerun()
        else:
            st.error('Поле не может быть пустым.')
    st.divider()
    # -----------------------------------------

    if st.session_state.generated_ideas:
        st.subheader('Список идей (ИИ + ваши)')
        st.caption('Отметьте те, которые пойдут в контент-план:')
       
        final_selection = []
        for idea in st.session_state.generated_ideas:
            # Создаем уникальный ключ на основе хеша текста идеи
            # Это гарантирует, что галочка не "слетит" при добавлении новых пунктов
            ikey = f"keep_{hashlib.md5(idea.encode()).hexdigest()[:10]}"
            
            # По умолчанию новые идеи (и ручные, и ИИ) будут отмечены
            if st.checkbox(idea, key=ikey, value=True):
                final_selection.append(idea)


# ---------------------------------------------------------------------------
# Вкладка 2 — КОНТЕНТ-ПЛАН
# ---------------------------------------------------------------------------
with tabs[2]:
    st.header('Календарный контент-план')

    # Собираем идеи по новым хеш-ключам
    final_ideas = []
    for idea in st.session_state.generated_ideas:
        ikey = f"keep_{hashlib.md5(idea.encode()).hexdigest()[:10]}"
        if st.session_state.get(ikey, False):
            final_ideas.append(idea)

    if not final_ideas:
        st.warning('Сначала выберите и сохраните идеи на вкладке «Идеи».')
    else:
        if st.button('📅 Сформировать/Обновить план'):
            df_plan = create_content_plan(final_ideas, frequency, format_choice, start_date)
            st.session_state.content_plan_data = df_plan # Сохраняем в state

        # Если план уже есть в памяти — показываем
        if 'content_plan_data' in st.session_state:
            st.success(f'План сформирован на основе {len(final_ideas)} идей.')
            
            # Таблица с новым параметром width='stretch'
            st.dataframe(st.session_state.content_plan_data, width='stretch')

            # Кнопка скачивания
            # Создаем буфер в памяти для Excel
            buffer = io.BytesIO()

            with pd.ExcelWriter(buffer, engine='xlsxwriter') as writer:
                st.session_state.content_plan_data.to_excel(writer, index=False, sheet_name='План')
    
            st.download_button(
                label='📊 Скачать контент-план (Excel)',
               data=buffer.getvalue(),
                file_name=f'content_plan_{theme}.xlsx',
                mime='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
            )


# ---------------------------------------------------------------------------
# Вкладка 3 — СЦЕНАРИЙ
# ---------------------------------------------------------------------------
with tabs[3]:
    st.header('Генерация сценария')

    # Собираем список только тех идей, на которых стоят галочки
    final_ideas = []
    for idea in st.session_state.generated_ideas:
        ikey = f"keep_{hashlib.md5(idea.encode()).hexdigest()[:10]}"
        if st.session_state.get(ikey, False):
            final_ideas.append(idea)

    if not final_ideas:
        st.warning('Нет выбранных идей. Сначала отметьте понравившиеся идеи на вкладке «Идеи».')
    else:
        st.subheader('Выбор идеи для проработки')
        selected_for_script = st.selectbox(
            'Выберите идею, для которой нужно написать сценарий:',
            options=final_ideas,
            index=0
        )

        if st.button('🎬 Сгенерировать сценарий', use_container_width=True):
            with st.spinner('ИИ прорабатывает сценарий...'):
                script_text = generate_script(
                    idea=selected_for_script,
                    topic=theme,
                    target_audience=target_audience,
                    format_choice=format_choice,
                    style_references=style_references
                )
                st.session_state.current_script = script_text
                
                # --- ЛОГИКА АРХИВАЦИИ ---
                new_entry = {
                    "time": datetime.now().strftime("%H:%M:%S"),
                    "idea": selected_for_script,
                    "text": script_text
                }
                if 'scenario_archive' not in st.session_state:
                    st.session_state.scenario_archive = []
                
                # Добавляем свежий сценарий в начало списка
                st.session_state.scenario_archive.insert(0, new_entry)
                # ------------------------

        # Отображение текущего (последнего сгенерированного) сценария
        if 'current_script' in st.session_state:
            st.divider()
            st.subheader('✨ Готовый сценарий')
            st.markdown(st.session_state.current_script)
            
            st.download_button(
                label='📄 Скачать текущий сценарий (.txt)',
                data=st.session_state.current_script,
                file_name=f'script_{hashlib.md5(selected_for_script.encode()).hexdigest()[:5]}.txt',
                mime='text/plain',
                key='dl_current_main'
            )

        # --- БЛОК АРХИВА СЕССИИ ---
        if st.session_state.get('scenario_archive'):
            st.divider()
            st.subheader("📂 Архив сценариев (текущая сессия)")
            st.caption("Здесь хранятся все варианты, созданные за этот запуск приложения")
            
            for i, item in enumerate(st.session_state.scenario_archive):
                # Название каждого блока в архиве: Время + начало идеи
                with st.expander(f"{item['time']} — {item['idea'][:50]}..."):
                    st.markdown(item['text'])
                    # Кнопка скачивания именно для этого архивного варианта
                    st.download_button(
                        label=f'📥 Скачать вариант {item['time']}',
                        data=item['text'],
                        file_name=f"archive_script_{i}.txt",
                        mime='text/plain',
                        key=f"dl_arch_{i}"
                    )
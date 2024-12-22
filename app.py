from flask import Flask, render_template, request, session, redirect, url_for
import requests
import os
from dotenv import load_dotenv
from flask_caching import Cache
import logging
import dash
from dash import dcc, html
from dash.dependencies import Input, Output
import plotly.graph_objs as go
import json

# Загрузка переменных из .env
load_dotenv()

app = Flask(__name__)
app.secret_key = os.urandom(24)  # Необходимо для использования сессий

# Настройка кэширования
cache = Cache(app, config={"CACHE_TYPE": "simple"})

# Получение API-ключа из переменных окружения
API_KEY = os.getenv("ACCUWEATHER_API_KEY")

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def get_location_key_by_city(city):
    # Получает уникальный ключ локации по названию города.
    params = {"apikey": API_KEY, "q": city}
    try:
        response = requests.get(
            "https://dataservice.accuweather.com/locations/v1/cities/search",
            params=params,
            timeout=5
        )
        response.raise_for_status()
        data = response.json()
        if data:
            return data[0].get("Key")
        else:
            return None
    except requests.exceptions.HTTPError as http_err:
        logger.error(
            f"HTTP error occurred при запросе locationKey для города {city}: {http_err}"
        )
    except requests.exceptions.ConnectionError as conn_err:
        logger.error(
            f"Ошибка соединения при запросе locationKey для города {city}: {conn_err}"
        )
    except requests.exceptions.Timeout as timeout_err:
        logger.error(
            f"Тайм-аут при запросе locationKey для города {city}: {timeout_err}"
        )
    except requests.exceptions.RequestException as req_err:
        logger.error(
            f"Произошла ошибка при запросе locationKey для города {city}: {req_err}"
        )
    return None


def check_bad_weather(temperature, wind_speed, precipitation_probability):
    # Функция для оценки погодных условий.
    conditions = []
    if temperature < -15 or temperature > 35:
        conditions.append("Температура слишком низкая или высокая")
    if wind_speed > 50:
        conditions.append("Сильный ветер")
    if precipitation_probability > 60:
        conditions.append("Высокая вероятность осадков")
    
    if conditions:
        return "Плохие погодные условия: " + ", ".join(conditions)
    return "Хорошие погодные условия"


@cache.memoize(timeout=3600)
def get_weather(location_key, days=5):
    # Получает прогноз погоды по locationKey на заданное количество дней.
    url = f"https://dataservice.accuweather.com/forecasts/v1/daily/{days}day/{location_key}"
    params = {"apikey": API_KEY, "details": "true", "metric": "true"}
    try:
        response = requests.get(url, params=params, timeout=5)
        response.raise_for_status()
        data = response.json()
        forecasts = data.get("DailyForecasts", [])
        
        weather_data = []
        for forecast in forecasts:
            day_weather = {
                "date": forecast.get("Date", "N/A")[:10],  # Формат YYYY-MM-DD
                "temperature_max": forecast.get("Temperature", {}).get("Maximum", {}).get("Value", "N/A"),
                "temperature_min": forecast.get("Temperature", {}).get("Minimum", {}).get("Value", "N/A"),
                "real_feel_max": forecast.get("RealFeelTemperature", {}).get("Maximum", {}).get("Value", "N/A"),
                "humidity": forecast.get("RealFeelTemperature", {}).get("Maximum", {}).get("Value", "N/A"),
                "wind_speed": forecast.get("Day", {}).get("Wind", {}).get("Speed", {}).get("Value", "N/A"),
                "precipitation_probability": forecast.get("Day", {}).get("PrecipitationProbability", "N/A"),
                "uv_index": forecast.get("UVIndex", "N/A"),
                "weather_text": forecast.get("Day", {}).get("IconPhrase", "N/A"),
            }
            
            weather_condition = check_bad_weather(
                day_weather["temperature_max"],
                day_weather["wind_speed"],
                day_weather["precipitation_probability"],
            )
            day_weather["weather_condition"] = weather_condition
            weather_data.append(day_weather)
        
        return weather_data
    except requests.exceptions.HTTPError as http_err:
        logger.error(f"HTTP error при запросе погоды для locationKey {location_key}: {http_err}")
    except requests.exceptions.ConnectionError as conn_err:
        logger.error(f"Ошибка соединения при запросе погоды для locationKey {location_key}: {conn_err}")
    except requests.exceptions.Timeout as timeout_err:
        logger.error(f"Тайм-аут при запросе погоды для locationKey {location_key}: {timeout_err}")
    except requests.exceptions.RequestException as req_err:
        logger.error(f"Произошла ошибка при запросе погоды для locationKey {location_key}: {req_err}")
    return None


@app.route("/", methods=["GET", "POST"])
def index():
    # Главная страница приложения
    weather = None
    if request.method == "POST":
        start_city = request.form.get("start_city")
        end_city = request.form.get("end_city")

        if start_city and end_city:
            try:
                # Получение locationKey для начальной и конечной точек
                start_location_key = get_location_key_by_city(start_city)
                end_location_key = get_location_key_by_city(end_city)

                if not start_location_key and not end_location_key:
                    weather = {
                        "error": "Оба города не найдены. Проверьте правильность введённых названий."
                    }
                elif not start_location_key:
                    weather = {
                        "error": f'Начальная точка "{start_city}" не найдена. Проверьте правильность названия.'
                    }
                elif not end_location_key:
                    weather = {
                        "error": f'Конечная точка "{end_city}" не найдена. Проверьте правильность названия.'
                    }
                else:
                    # Получение прогноза погоды для начальной и конечной точек
                    start_weather = get_weather(start_location_key)
                    end_weather = get_weather(end_location_key)

                    if start_weather and end_weather:
                        # Сохранение данных в сессию
                        session['weather'] = {
                            "start_weather": start_weather,
                            "end_weather": end_weather,
                            "start_city": start_city,
                            "end_city": end_city
                        }
                        weather = {
                            "start_weather": start_weather,
                            "end_weather": end_weather,
                        }
                    else:
                        weather = {
                            "error": "Не удалось получить данные о погоде для одной из точек."
                        }

            except Exception as e:
                logger.error(f"Ошибка при обработке запроса: {e}")
                weather = {
                    "error": "Произошла внутренняя ошибка. Пожалуйста, попробуйте позже."
                }
    return render_template("index.html", weather=weather)


# Интеграция Dash
dash_app = dash.Dash(
    __name__,
    server=app,
    url_base_pathname='/dash/',
    external_stylesheets=['https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css']
)

def create_dash_layout():
    return html.Div([
        html.H1("Визуализация прогноза погоды", style={'textAlign': 'center', 'color': '#4169E1'}),
        dcc.Dropdown(
            id='city-dropdown',
            options=[
                {'label': 'Начальная точка', 'value': 'start'},
                {'label': 'Конечная точка', 'value': 'end'}
            ],
            value='start',
            style={'width': '50%', 'margin': 'auto', 'marginBottom': '20px'}
        ),
        dcc.Graph(id='temperature-graph'),
        dcc.Graph(id='precipitation-graph')
    ], className='container')

dash_app.layout = create_dash_layout

@dash_app.callback(
    [Output('temperature-graph', 'figure'),
     Output('precipitation-graph', 'figure')],
    [Input('city-dropdown', 'value')]
)
def update_graphs(selected_point):
    # Получение данных из Flask-сессии
    weather = session.get('weather')

    if not weather:
        return go.Figure(), go.Figure()

    if selected_point == 'start':
        city_weather = weather.get('start_weather', [])
        city_name = weather.get('start_city', "Начальная точка")
    else:
        city_weather = weather.get('end_weather', [])
        city_name = weather.get('end_city', "Конечная точка")
    
    # Извлечение данных
    dates = [day['date'] for day in city_weather]
    temps_max = [day['temperature_max'] for day in city_weather]
    temps_min = [day['temperature_min'] for day in city_weather]
    precipitation = [day['precipitation_probability'] for day in city_weather]

    # График температур
    temp_fig = go.Figure()
    temp_fig.add_trace(go.Scatter(
        x=dates,
        y=temps_max,
        mode='lines+markers',
        name='Максимальная температура',
        line=dict(color='#FF5733')
    ))
    temp_fig.add_trace(go.Scatter(
        x=dates,
        y=temps_min,
        mode='lines+markers',
        name='Минимальная температура',
        line=dict(color='#33C1FF')
    ))
    temp_fig.update_layout(
        title=f'Прогноз температуры для {city_name}',
        xaxis_title='Дата',
        yaxis_title='Температура (°C)',
        template='plotly_white'
    )

    # График вероятности осадков
    precip_fig = go.Figure()
    precip_fig.add_trace(go.Bar(
        x=dates,
        y=precipitation,
        name='Вероятность осадков',
        marker_color='#42f44b'
    ))
    precip_fig.update_layout(
        title=f'Вероятность осадков для {city_name}',
        xaxis_title='Дата',
        yaxis_title='Вероятность осадков (%)',
        template='plotly_white'
    )

    return temp_fig, precip_fig

if __name__ == "__main__":
    app.run(debug=True)

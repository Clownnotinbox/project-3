from flask import Flask, render_template, request
import requests
import os
from dotenv import load_dotenv
from flask_caching import Cache
import logging

# Загрузка переменных из .env
load_dotenv()

app = Flask(__name__)

# Настройка кэширования
cache = Cache(app, config={"CACHE_TYPE": "simple"})

# Получение API-ключа из переменных окружения
API_KEY = os.getenv("ACCUWEATHER_API_KEY")

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def get_location_key_by_city(city):
    #Получает уникальный ключ локации  по названию города.
    params = {"apikey": API_KEY, "q": city}
    try:
        response = requests.get("http://dataservice.accuweather.com/locations/v1/cities/search", params=params, timeout=5)
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
    #Функция для оценки погодных условий.
    if temperature < -15 or temperature > 35:  # Температура слишком низкая или высокая
        return "Плохие погодные условия"
    if wind_speed > 50:  # Сильный ветер
        return "Плохие погодные условия"
    if precipitation_probability > 60:  # Высокая вероятность осадков
        return "Плохие погодные условия"

    return "Хорошие погодные условия"


@cache.memoize(timeout=3600)
def get_weather(location_key):
    #Получает прогноз погоды по locationKey.
    url = f"http://dataservice.accuweather.com/forecasts/v1/daily/1day/{location_key}"
    params = {"apikey": API_KEY, "details": "true", "metric": "true"}
    try:
        response = requests.get(url, params=params, timeout=5)
        response.raise_for_status()
        data = response.json()
        forecast = data.get("DailyForecasts", [])[0]

        weather_data = {
            "temperature": forecast["Temperature"]["Maximum"][
                "Value"
            ],  # Температура в Цельсиях
            "humidity": forecast.get("RealFeelTemperature", {})
            .get("Maximum", {})
            .get("Value", "N/A"),  # Влажность
            "wind_speed": forecast["Day"]["Wind"]["Speed"]["Value"],  # Скорость ветра
            "precipitation_probability": forecast["Day"][
                "PrecipitationProbability"
            ],  # Вероятность дождя
        }
        # Оценка погодных условий
        weather_condition = check_bad_weather(
            weather_data["temperature"],
            weather_data["wind_speed"],
            weather_data["precipitation_probability"],
        )
        weather_data["weather_condition"] = weather_condition

        return weather_data
    except requests.exceptions.HTTPError as http_err:
        logger.error(
            f"HTTP error occurred при запросе погоды для locationKey {location_key}: {http_err}"
        )
    except requests.exceptions.ConnectionError as conn_err:
        logger.error(
            f"Ошибка соединения при запросе погоды для locationKey {location_key}: {conn_err}"
        )
    except requests.exceptions.Timeout as timeout_err:
        logger.error(
            f"Тайм-аут при запросе погоды для locationKey {location_key}: {timeout_err}"
        )
    except requests.exceptions.RequestException as req_err:
        logger.error(
            f"Произошла ошибка при запросе погоды для locationKey {location_key}: {req_err}"
        )
    return None


@app.route("/", methods=["GET", "POST"])
def index():
    #Главная страница приложения
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
                        # Оценка погодных условий для обеих точек
                        weather = {
                            "start_temperature": start_weather["temperature"],
                            "end_temperature": end_weather["temperature"],
                            "start_weather_condition": start_weather[
                                "weather_condition"
                            ],
                            "end_weather_condition": end_weather["weather_condition"],
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


if __name__ == "__main__":
    app.run(debug=True)

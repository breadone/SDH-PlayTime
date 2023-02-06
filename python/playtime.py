from datetime import timedelta
from datetime import datetime, date, timedelta
import logging
from storage import Storage, OldVersionException
from functools import reduce


DATE_FORMAT = "%Y-%m-%d"
logger = logging.getLogger()


class PlayTime:
    """
    Internal dict format of the storage
    {
        "2022-01-31": {
            "gameId": {
                "name" : "Game name",
                "time": 3600 // in seconds
            }
        }
    }
    """
    storage: Storage

    def __init__(self, storage: Storage) -> None:
        self.storage = storage

    async def get_play_time_statistics(self, start: date, end: date):
        (_, data) = await self.storage.get()

        result = []
        date_range = date_range_list(start, end)
        for day in date_range:
            date_to_include = day.strftime(DATE_FORMAT)
            if (date_to_include in data):
                day = data[date_to_include]
                games = []
                for key in data[date_to_include]:
                    games.append({
                        "gameId": key,
                        "gameName": day[key]["name"],
                        "time": day[key]["time"]
                    })
                result.append({
                    "date": date_to_include,
                    "games": games,
                    "totalTime": reduce(lambda a, b: a + b["time"], games, 0)
                })
            else:
                result.append({
                    "date": date_to_include,
                    "games": [],
                    "totalTime": 0
                })

        return result

    async def add_new_time(self, started_at: int, ended_at: int, game_id: str, game_name: str):
        logger.info(f"Adding new interval")
        day_end_for_start_at = timestamp_of_end_of_day(
            datetime.fromtimestamp(started_at))
        intervals = []
        if (started_at < day_end_for_start_at and ended_at > day_end_for_start_at):
            intervals.append(
                (started_at, day_end_for_start_at + 1, game_id, game_name))
            intervals.append(
                (day_end_for_start_at + 1, ended_at, game_id, game_name))
        else:
            intervals.append(
                (started_at, ended_at, game_id, game_name))

        for interval in intervals:
            (i_started_at, i_ended_at, i_game_id, i_game_name) = interval
            await retry_on_old_version_exception(
                tries=5,
                fun=lambda: self._add_new_time(i_started_at, i_ended_at,
                                               i_game_id, i_game_name)
            )

    async def _add_new_time(self, started_at: int, ended_at: int, game_id: str, game_name: str):
        (version, data) = await self.storage.get()
        interval_date = format_timestamp_as_date_only_string(started_at)
        interval_length_s = ended_at - started_at
        logger.info(
            f"Current data state before save: version={version}, data='{data}'")

        game_id_str = str(game_id)
        if (not interval_date in data):
            data[interval_date] = {
                game_id_str: {
                    "name": game_name,
                    "time": interval_length_s
                }
            }
        elif (not game_id_str in data[interval_date]):
            data[interval_date][game_id_str] = {
                "name": game_name,
                "time": interval_length_s
            }
        else:
            current_time = data[interval_date][game_id_str]["time"]
            data[interval_date][game_id_str]["time"] = current_time + \
                interval_length_s
        logger.info(f"Saving new state: version={version}, data='{data}'")
        await self.storage.save(version, data)


async def retry_on_old_version_exception(tries, fun):
    try:
        await fun()
    except OldVersionException:
        logger.warn(f"Old version detected, retrying with tries='{tries}'")
        if (tries > 0):
            retry_on_old_version_exception(tries - 1, fun)
        else:
            raise Exception(
                "Unable to save due to a lot of contention in storage")


def timestamp_of_end_of_day(day_to_end):
    result = datetime.combine(
        day_to_end + timedelta(days=1), datetime.min.time()
    )
    return int(result.timestamp()) - 1


def date_range_list(start_date, end_date):
    # Return list of datetime.date objects (inclusive) between start_date and end_date (inclusive).
    date_list = []
    curr_date = start_date
    while curr_date <= end_date:
        date_list.append(curr_date)
        curr_date += timedelta(days=1)
    return date_list


def format_timestamp_as_date_only_string(timestamp):
    return datetime.fromtimestamp(timestamp).strftime(DATE_FORMAT)

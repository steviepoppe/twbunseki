"""
Get different metrics for CSV file generated by twitter_search.py

For _media.csv files, we sometimes run into problems expanding URLs and in this case:
- expanded_url will be empty, and
- error_expanding will be "True"

Run:
- Install requirements (`$ pip install pandas`)
- Have csv file ready (generated by twitter_search.py)
- Run `$ python get_metrics.py --help` for exact arguments
"""
import asyncio
import argparse
import csv
from datetime import date, datetime
from dateutil import parser
import json
from pathlib import Path
import re
import requests
import sys
import time
from urllib.parse import urlparse

import aiohttp
import pandas as pd


async def parse_tweets(args):

	file_path = args['filename']
	timezone = args['timezone']  # example: 'Asia/Tokyo', 'UTC'
	keep_rt = not args['no_keep_rt']
	analyze_datetime = not args['no_analyze_datetime']
	analyze_users = not args['no_analyze_users']
	analyze_hashtags = not args['no_analyze_hashtags']
	analyze_hashtag_dates = analyze_hashtags
	analyze_urls = args['analyze_urls']
	exclude_twitter_urls = args['exclude_twitter_urls']
	chunksize = args['chunk_size']
	max_redirect_depth = args['max_redirect_depth']
	from_date = args['from_date']
	to_date = args['to_date']
	sep = args['csv_sep']
	hashtags = {}
	hashtag_dates = {}
	date_set = {}
	time_set = {}
	user_set = {}
	media_set = {}
	line_count = 0
	skipped_tweets = {}  # reason: count
	warnings = set()

	file_name = file_path.split('/')[-1].replace('.csv', '')

	save_file_name = file_name
	if from_date:
		save_file_name += f'_from:{from_date}'
	if to_date:
		save_file_name += f'_to:{to_date}'
	
	Path("./results/metrics_%s/" % save_file_name).mkdir(parents=True, exist_ok=True)

	for chunk in pd.read_csv(file_path, encoding="utf-8", chunksize=chunksize, iterator=True, sep=sep):
		# time filtering and timezone conversion
		chunk.created_at = pd.to_datetime(chunk.created_at, utc=True)
		if timezone is not None:
			chunk.created_at = chunk.created_at.dt.tz_convert(tz=timezone)
		if from_date is not None:
			chunk = chunk[chunk.created_at >= from_date]
		if to_date is not None:
			chunk = chunk[chunk.created_at <= to_date]
		chunk.created_at = chunk.created_at.apply(str)

		# warnings
		if 'hashtags' not in chunk and analyze_hashtags:
			analyze_hashtags = False
			analyze_hashtag_dates = False
			warnings.add('"hashtags" column is required to analyze hashtags. Skipping.')
		if 'created_at' not in chunk:
			if analyze_hashtag_dates:
				analyze_hashtag_dates = False
				warnings.add('"created_at" column is required to analyze hashtags by date. Skipping.')
			if analyze_datetime:
				analyze_datetime = False
				warnings.add('"created_at" column is required to analyze date and time metrics. Skipping.')
		if 'text' not in chunk and analyze_urls:
			analyze_urls = False
			warnings.add('"text" column is required to analyze media URLs. Skipping.')	
		if 'user_screen_name' not in chunk and analyze_users:
			analyze_users = False
			warnings.add('"user_screen_name" column is required to analyze user metrics. Skipping.')

		for index, tweet in chunk.iterrows():
			line_count += 1
			is_retweet = 1 if tweet.get('is_retweet', False) == True else 0

			if is_retweet and not keep_rt:
				reason = 'Retweets while keep-rt is set to False'
				skipped_tweets[reason] = skipped_tweets.get(reason, 0) + 1
				continue

			if analyze_hashtags:
				hashtag_metrics(tweet, hashtags, is_retweet)
				hashtag_date_metrics(tweet, hashtag_dates, is_retweet)
			if analyze_datetime:
				date_metrics(tweet, date_set, is_retweet)
				time_metrics(tweet, time_set, is_retweet)
			if analyze_users:
				user_metrics(tweet, user_set, is_retweet)
			if analyze_urls:
				media_metrics(tweet, media_set, is_retweet)
		if analyze_urls:
			await expand_media_urls(media_set, exclude_twitter_urls, max_redirect_depth)
		print('Processed %s lines.' % line_count)
		
	print('Processed total of %s lines.' % line_count)
	if skipped_tweets:
		for reason, number in skipped_tweets.items():
			warnings.add(f'Skipped {number} tweet(s). Reason: "{reason}"')
	for warning in warnings:
		print(f'WARNING: {warning}')

	if analyze_hashtags:
		save_hashtag_metrics(hashtags, save_file_name)
		save_hashtag_date_metrics(hashtag_dates, save_file_name)
	if analyze_datetime:
		save_date_metrics(date_set, save_file_name)
		save_time_metrics(time_set, save_file_name)
	if analyze_users:
		save_user_metrics(user_set, save_file_name)
	if analyze_urls:
		save_media_metrics(media_set, save_file_name)


def get_initial_retweet_stat_matrix(is_retweet):
	retweet_stats = [0, 0, [[],[]]]  # [number of og tweets, number of retweets, [list_of_og_tweeters, list_of_retweeters]]
	retweet_stats[is_retweet] = 1
	retweet_stats[not is_retweet] = 0
	return retweet_stats


def hashtag_metrics(tweet, hashtags, is_retweet):
	if not pd.isna(tweet["hashtags"]):
		c_hashtags = tweet["hashtags"].replace(",,",",").split(",") # possibility of empty strings joined = two commas
		for hashtag in c_hashtags:						
			if hashtag != '':
				if hashtag in hashtags:
					hashtags[hashtag][is_retweet] = hashtags[hashtag][is_retweet] + 1
				else:
					retweet_stats = get_initial_retweet_stat_matrix(is_retweet)
					hashtags[hashtag] = retweet_stats
				if 'user_screen_name' in tweet:
					hashtags[hashtag][2][is_retweet].append(tweet["user_screen_name"])


def hashtag_date_metrics(tweet, hashtag_dates, is_retweet):
	tweet_created_month = parser.parse(tweet["created_at"]).strftime("%m/%Y") # month/year
	if not pd.isna(tweet["hashtags"]):
		c_hashtags = tweet["hashtags"].replace(",,",",").split(",") # possibility of empty strings joined = two commas
		for hashtag in c_hashtags:						
			if hashtag != '':
				if hashtag_dates.get(hashtag, {}).get(tweet_created_month) is not None:
					hashtag_dates[hashtag][tweet_created_month][is_retweet] = hashtag_dates[hashtag][tweet_created_month][is_retweet] + 1
				else:
					retweet_stats = get_initial_retweet_stat_matrix(is_retweet)
					if hashtag not in hashtag_dates:
						hashtag_dates[hashtag] = {}
					hashtag_dates[hashtag][tweet_created_month] = retweet_stats
				if 'user_screen_name' in tweet:
					hashtag_dates[hashtag][tweet_created_month][2][is_retweet].append(tweet["user_screen_name"])

def date_metrics(tweet, date_set, is_retweet):
	#print(tweet["created_at"])
	tweet_created_date = parser.parse(tweet["created_at"]).strftime("%m/%d/%Y")
#	print(tweet_created_date.strftime("%m/%d/%Y"))
#	tweet_created_date = datetime.fromisoformat(tweet_created_date).strftime("%m/%d/%Y")
	if not tweet_created_date in date_set:
		retweet_stats = get_initial_retweet_stat_matrix(is_retweet)
		date_set[tweet_created_date] = retweet_stats
	else:
		date_set[tweet_created_date][is_retweet] += 1
	if 'user_screen_name' in tweet:
		date_set[tweet_created_date][2][is_retweet].append(tweet["user_screen_name"])

def time_metrics(tweet, time_set, is_retweet):
	tweet_created_time = parser.parse(tweet["created_at"]).strftime("%H")  #change to %I %p for AM/PM

	if not tweet_created_time in time_set:
		retweet_stats = get_initial_retweet_stat_matrix(is_retweet)
		time_set[tweet_created_time] = retweet_stats
	else:
		time_set[tweet_created_time][is_retweet] += 1
	if 'user_screen_name' in tweet:
		time_set[tweet_created_time][2][is_retweet].append(tweet["user_screen_name"])


def media_metrics(tweet, media_set, is_retweet):
	pattern = re.compile(r'.*(https://t.co/[a-zA-Z0-9]+).*')
	result = pattern.match(tweet['text'])
	if result is None:
		return
	
	url = result[1]
	if url in media_set:
		media_set[url]['metrics'][is_retweet] += 1
	else:
		media_set[url] = {}
		media_set[url]['metrics'] = [0, 0]  # [tweets, retweets]
		media_set[url]['metrics'][is_retweet] = 1


async def expand_media_urls(media_set, exclude_twitter_urls, max_redirect_depth):
	async with aiohttp.ClientSession() as session:
		tasks = []
		for url in media_set:
			if 'expanded' not in media_set[url]:
				tasks.append(asyncio.ensure_future(expand_url(session, url, max_redirect_depth)))
		expanded_urls = await asyncio.gather(*tasks)
	for url, expanded, error, domain in expanded_urls:
		if expanded.startswith('https://twitter.com/') and exclude_twitter_urls:
			media_set.pop(url, None)
			continue
		media_set[url]['error_expanding'] = error
		media_set[url]['expanded'] = expanded
		media_set[url]['domain'] = domain


async def expand_url(session, url, max_redirect_depth):
	expanded = ''
	domain = ''
	redirect = 0
	next_url = url
	try:
		while redirect < max_redirect_depth:
			async with session.head(next_url, allow_redirects=False) as res:
				next_url = res.headers.get('location', '')
			if next_url == '':
				break
			if next_url.startswith('/'):
				next_url =  'https://' + domain + next_url
			expanded = next_url
			domain = urlparse(expanded).netloc or domain  # if no domain, keep last known domain
			redirect += 1
	except Exception:
		pass
	error = expanded == ''
	return url, expanded, error, domain

def user_metrics(tweet, user_set, is_retweet):
	if tweet["user_screen_name"] not in user_set:
		user = {}
		user["screen_name"] = tweet["user_screen_name"]
		user["description"] = tweet.get("user_description", "")
		user["following_count"] = tweet.get("user_following_count", -1)
		user["followers_count"] = tweet.get("user_followers_count", -1)
		user["total_tweets"] = tweet.get("user_total_tweets", -1)
		user["created_at"] = tweet.get("user_created_at", '')
		user["total_in_data_set"] = [0,0]
		user["total_in_data_set"][is_retweet] = 1
		user_set[tweet["user_screen_name"]] = user

	else:			
		user_set[tweet["user_screen_name"]]["total_in_data_set"][is_retweet] += 1
		if tweet["user_following_count"] > user_set[tweet["user_screen_name"]]["following_count"]:
			user_set[tweet["user_screen_name"]]["following_count"] 
		if tweet["user_followers_count"] > user_set[tweet["user_screen_name"]]["followers_count"]:
			user_set[tweet["user_screen_name"]]["followers_count"] 
		if tweet["user_total_tweets"] > user_set[tweet["user_screen_name"]]["total_tweets"]:
			user_set[tweet["user_screen_name"]]["total_tweets"] 


def save_hashtag_metrics(hashtags, file_name):
	with open('./results/metrics_%s/%s_hashtags.csv' % (file_name, file_name), 
		mode='w', encoding="utf-8",newline='') as file_hashtags:
		writer_hashtags = csv.writer(file_hashtags)
		writer_hashtags.writerow(["hashtag","total_normal", "total_retweet", 
			"total","unique_tweeters", "re_unique_tweeters", "re_unique_tweeters_filtered", "total"])

		for hashtag, value in hashtags.items():
			normal = set(value[2][0])
			retweet = set(value[2][1])
			unique = [x for x in retweet if x not in normal]
			writer_hashtags.writerow([hashtag, value[0], value[1], value[0] + value[1], str(len(normal)), 
				str(len(retweet)), str(len(unique)), str(len(normal) + len(unique))])
	print("Finished. Saved to ./results/metrics_%s/%s_hashtags.csv" % (file_name, file_name))


def save_hashtag_date_metrics(hashtag_dates, file_name):
	with open('./results/metrics_%s/%s_hashtag_dates.csv' % (file_name, file_name), 
		mode='w', encoding="utf-8",newline='') as file_hashtags:
		writer_hashtags = csv.writer(file_hashtags)
		writer_hashtags.writerow(["hashtag", "month", "total_normal", "total_retweet", 
			"total","unique_tweeters", "re_unique_tweeters", "re_unique_tweeters_filtered", "total"])

		for hashtag, months in hashtag_dates.items():
			for month, value in months.items():
				normal = set(value[2][0])
				retweet = set(value[2][1])
				unique = [x for x in retweet if x not in normal]
				writer_hashtags.writerow([hashtag, month, value[0], value[1], value[0] + value[1], str(len(normal)), 
					str(len(retweet)), str(len(unique)), str(len(normal) + len(unique))])
	print("Finished. Saved to ./results/metrics_%s/%s_hashtag_dates.csv" % (file_name, file_name))


def save_date_metrics(date_set, file_name):
	with open('./results/metrics_%s/%s_date.csv' % (file_name, file_name), 
		mode='w', encoding="utf-8",newline='') as file_date:
		writer_date = csv.writer(file_date)
		writer_date.writerow(["date","total_normal", "total_retweet", "total_tweets","unique_normal_tweeters",
			"unique_retweeters_exist", "unique_retweeters_filtered", "unique_retweeters_total", 
			"total_tweeters"])

		for date, value in date_set.items():
			#unique_users[is_retweet]

			normal = set(value[2][0])
			retweet = set(value[2][1])
			unique = [x for x in retweet if x not in normal]
			writer_date.writerow([date, value[0], value[1], value[0] + value[1], 
				str(len(normal)), str(len(retweet) - len(unique)), str(len(unique)), str(len(retweet)), 
				str(len(normal) + len(unique))])

	print("Finished. Saved to ./results/metrics_%s/%s_date.csv" % (file_name, file_name))


def save_time_metrics(time_set, file_name):
	with open('./results/metrics_%s/%s_time.csv' % (file_name, file_name), 
		mode='w', encoding="utf-8",newline='') as file_time:
		writer_time = csv.writer(file_time)
		writer_time.writerow(["time","total_normal", "total_retweet", "total_tweets","unique_tweeters", 
			"re_unique_tweeters", "re_unique_tweeters_filtered", "total_tweeters"])

		for hour, value in time_set.items():
			normal = set(value[2][0])
			retweet = set(value[2][1])
			unique = [x for x in retweet if x not in normal]
			writer_time.writerow([hour, value[0], value[1], value[0] + value[1], 
				str(len(normal)), str(len(retweet)), str(len(unique)), str(len(normal) + len(retweet))])
	print("Finished. Saved to ./results/metrics_%s/%s_time.csv" % (file_name, file_name))


def save_media_metrics(media_set, file_name):
	with open('./results/metrics_%s/%s_media.csv' % (file_name, file_name),
		mode='w', encoding='utf-8', newline='') as file_media:
		writer_media = csv.writer(file_media)
		writer_media.writerow(['url', 'expanded_url', 'domain', 'error_expanding', 'total_tweets', 'total_retweet'])

		for url, value in media_set.items():
			try:
				writer_media.writerow([url, value['expanded'], value['domain'], str(value['error_expanding']), str(value['metrics'][0]), str(value['metrics'][1])])
			except Exception:
				writer_media.writerow([url, '', '', str(True), str(value['metrics'][0]), str(value['metrics'][1])])
	print('Finished. Saved to ./results/metrics_%s/%s_media.csv' % (file_name, file_name))


def save_user_metrics(user_set, file_name):
	with open('./results/metrics_%s/%s_users.csv' % (file_name, file_name), 
		mode='w', encoding="utf-8",newline='') as file_users:
		writer_users = csv.writer(file_users)
		writer_users.writerow(["screen_name", "total_posted_normal","total_posted_retweets","total_posted", 
			"user_description","user_following_count", "user_followers_count", "user_total_tweets","user_created_at"])

		for a in user_set:
			user = user_set[a]
			writer_users.writerow([user["screen_name"],user["total_in_data_set"][0],user["total_in_data_set"][1], 
				(user["total_in_data_set"][0] + user["total_in_data_set"][1]), user["description"],
				user["following_count"],user["followers_count"],user["total_tweets"],user["created_at"]])

	print("Finished. Saved to ./results/metrics_%s/%s_users.csv" % (file_name, file_name))


if __name__ == '__main__':
	p = argparse.ArgumentParser(description='Analyze metrics for a Twitter corpus w/ format compatible with twitter_search.py')
	p.add_argument(
		'-f',
		'--filename',
		type=str,
		required=True,
		help='Full or relative path to the csv file. E.g. results/my_data.csv',
	)
	p.add_argument(
		'-c',
		'--chunk-size',
		type=int,
		default=100000,
		help='Size of processing chunk. Default: 100K rows'
	)
	p.add_argument(
		'-tz',
		'--timezone',
		type=str,
		help='Timezone to convert time data to before analysis (does not impact original file) e.g. Asia/Tokyo (Optional)',
	)
	p.add_argument(
		'--analyze-urls',
		action='store_true',
		help='Use this to process/expand media/URLs'
	)
	p.add_argument(
		'--exclude-twitter-urls',
		action='store_true',
		help='Use this to exclude any url that expands to https://twitter.com/*'
	)
	p.add_argument(
		'--no-keep-rt',
	   	action='store_true',
		help='Use this to NOT process RTs',
	)
	p.add_argument(
		'--no-analyze-hashtags',
		action='store_true',
		help='Use this to NOT process hashtags'
	)
	p.add_argument(
		'--no-analyze-datetime',
		action='store_true',
		help='Use this to NOT process dates and times'
	)
	p.add_argument(
		'--no-analyze-users',
		action='store_true',
		help='Use this to NOT process users'
	)
	p.add_argument(
		'--max-redirect-depth',
		type=int,
		default=1,
		help='Max depth to follow redirects when analyzing URLs. Default is the minimum: 1 (get link after t.co). WARNING: exponentially slower with each added layer of depth'
	)
	p.add_argument(
		'--from-date',
		type=str,
		help='Format: YYYY-MM-DD. Use only if you want to limit processing from a certain date (not datetime)'
	)
	p.add_argument(
		'--to-date',
		type=str,
		help='Format: YYYY-MM-DD. Use only if you want to limit processing to a certain date (not datetime)'
	)
	p.add_argument(
		'--csv-sep',
		type=str,
		default=',',
		choices=[',', ';', '\\t', '|'],
		help='Separator for your csv file. Default: ","',
	)

	args = vars(p.parse_args())
	
	asyncio.run(parse_tweets(args))

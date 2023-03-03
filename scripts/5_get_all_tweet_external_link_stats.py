import pandas as pd
import csv

import tldextract


def get_domain(url):
	if type(url) is str:
		return tldextract(url).domain
	return ''


def get_all_tweet_stats(args):
	corpus_filename = args['corpus_filename']
	dictionary_filename = args['dictionary_filename']
	tweet_links_filename = args['tweet_links_filename ']
	output_filename = args['output_filename']
	csv_sep = args['csv_sep']

	print(f'Reading corpus csv from {corpus_filename}...')
	corpus = pd.read_csv(corpus_filename, sep=csv_sep)

	# drop accidental duplicates in corpus
	before = len(corpus)
	corpus = corpus.drop_duplicates()
	after = len(corpus)
	diff = before - after
	if diff > 0:
		print(f'> found {diff} duplicates in corpus, dropped them in-memory (input file was not affected).')

	print(f'Reading dictionary csv from {dictionary_filename}...')
	dictionary_df = pd.read_csv(dictionary_filename)

	print(f'> getting domains without suffixes for all dictionary expanded URLs...')
	dictionary_df['_domain'] = dictionary_df['expanded_url'].apply(get_domain)

	print(f'Reading tweet links csv from {tweet_links_filename}...')
	tweet_links_df = pd.read_csv(tweet_links_filename)

	print(f'> getting tweet_ids for all tweets linking to external media...')
	merged_df = tweet_links_df.merge(dictionary_df[['url', '_domain']], on='url', how='left')

	print(f'> excluding all twitter links from analysis..')
	merged_df = merged_df[merged_df['_domain'] != 'twitter']

	corpus['has_external_link'] = corpus['tweet_id'].isin(merged_df.tweet_id)
	
	print(f'Constructing final dataframe...')
	final_df = corpus[['tweet_id', 'user_screen_name', 'tweet_retweet_count', 'created_at', 'has_external_link']]

	save_file_name = output_filename.removesuffix('.csv') + '_all_tweets_with_external_link_flag' + '.csv'
	print(f'Saving dataframe to {save_file_name}...')
	final_df.to_csv(save_file_name, mode='w+', index=False, encoding='utf-8', quoting=csv.QUOTE_NONNUMERIC)

	print(f'Extracting stats...')
	data = pd.DataFrame([
		{
			'type': 'all_tweets',
			'total_tweet_count': len(final_df),
			'total_retweet_count': final_df['tweet_retweet_count'].sum(),
			'unique_users': len(final_df['user_screen_name'].unique()),
		},
		{
			'type': 'tweets_with_external_links',
			'total_tweet_count': len(final_df[final_df['has_external_link']]),
			'total_retweet_count': final_df[final_df['has_external_link']]['tweet_retweet_count'].sum(),
			'unique_users': len(final_df[final_df['has_external_link']]['user_screen_name'].unique()),
		},
	])
	
	save_file_name = output_filename.removesuffix('.csv') + '_stats' + '.csv'
	print(f'Saving stats dataframe to {save_file_name}...')
	data.to_csv(save_file_name, mode='w+', index=False, encoding='utf-8', quoting=csv.QUOTE_NONNUMERIC)

	print('Done!')


if __name__ == '__main__':
	pd.options.mode.chained_assignment = None
	p = argparse.ArgumentParser(description='Get and aggregate data for Media URL metrics (more granular than get_metrics.py)')
	p.add_argument(
		'-cf',
		'--corpus-filename',
		type=str,
		required=True,
		help='Full or relative path to the full corpus csv file from twitter_search.py. E.g. results/my_data.csv',
	)
	p.add_argument(
		'-df',
		'--dictionary-filename',
		type=str,
		required=True,
		help='Full or relative path to the URL dictionary csv file from reanalyze_media.py (UNEDITED). E.g. results/my_data.csv',
	)
	p.add_argument(
		'-lf',
		'--tweet-links-filename',
		type=str,
		required=True,
		help='Full or relative path to the tweet links csv file from extract_media.py. E.g. results/my_data.csv',
	)
	p.add_argument(
		'-of',
		'--output-filename',
		type=str,
		required=True,
		help='Full or relative path store resulting csv files (will be edited with suffixes). E.g. results/my_data.csv',
	)
	p.add_argument(
		'--csv-sep',
		type=str,
		default=',',
		choices=[',', ';', '\\t', '|'],
		help='Separator for your corpus csv. Default: ","',
	)
	args = vars(p.parse_args())
	get_all_tweet_stats(args)
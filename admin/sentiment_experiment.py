"""
Unused reference code: sentiment analysis / topic extraction on inspection report PDFs.

This is exploratory work-in-progress, moved out of ofsted_ilacs_scrape.py to keep the
main pipeline script readable - see the README's "Future work" section. Nothing here
is imported or executed as part of the scrape; it's kept as a starting point for anyone
picking this work back up, verbatim from where it sat (commented out, unreachable) in
the main script.

Needs `textblob`, `nltk`, `gensim`, and `scikit-learn` installed - none of these are
part of this project's normal dependencies (pyproject.toml/uv.lock). On first use also
run:
    nltk.download('punkt')      # tokeniser models/sentence segmentation
    nltk.download('stopwords')  # stop words ready for text analysis/NLP preprocessing
    nltk.download('punkt_tab')  # work-around for textblob.exceptions.MissingCorpusError

These libraries (plus PyMuPDF, jinja2, pyyaml, networkx, pydot) were previously dropped
from ofsted_ilacs_scrape.py's dependency set as unused - reinstate whichever of them
this needs if the work is picked back up.
"""

import re

import nltk
import PyPDF2
from textblob import TextBlob
from gensim import corpora, models
from sklearn.metrics.pairwise import cosine_similarity
from sklearn.feature_extraction.text import CountVectorizer


# Sentiment analysis additional stop/ignore words
# bespoke stop words list (minimise uneccessary common non-informative words in the sentiment analysis)
report_sentiment_ignore_words = [
    # Words related to the organisation and nature of the report
    'ofsted', 'inspection', 'report',

    # Words related to the subjects of the report
    'child', 'children', 'children\'s', 'young', 'people',

    # Words related to the services involved
    'service', 'services', 'childrens services', 'social', 'care',

    # Words related to the providers of the services
    'staff', 'workers', 'managers',

    # Words related to performance and outcomes
    'achievement', 'achievements', 'outcome', 'outcomes', 'performance',
    'improvement', 'improvements',

    # Words related to measures and standards
    'assessment', 'assessments', 'standard', 'standards',
    'requirement', 'requirements', 'grade', 'grades',

    # Words related to the local authority and policy
    'local', 'authority', 'policy', 'policies',

    # Words related to specific aspects of care
    'help', 'support', 'provision', 'safeguarding', 'families',
    'work', 'leavers',

    # Other
    'year'
]


def get_sentiment_and_topics(pdf_buffer, ignore_words=[]):
    """
    Analyse the sentiment and extract the top 3 topics from a PDF document.

    This function takes a file-like buffer containing a PDF document as input and
    performs the following tasks:
    1. Reads the content of the PDF file using the PyPDF2 library.
    2. Extracts the text from each page and concatenates it into a single string.
    3. Performs sentiment analysis on the extracted text using the TextBlob library.
       The sentiment polarity score ranges from -1 (most negative) to 1 (most positive).
    4. Identifies key themes or topics from the extracted text using the Latent Dirichlet
       Allocation (LDA) model from the Gensim library.
    5. Returns the sentiment polarity score and the top 3 topics extracted from the PDF file.

    Args:
        pdf_buffer (io.BytesIO): A file(-like) buffer containing the PDF content.
        ignore_words (list): A list of words to be ignored during sentiment analysis(so we can remove common words)

    Returns:
        tuple: A tuple containing the sentiment polarity score (float) and a list of
               the top 3 topics (strings).
    """

    # Read the PDF stuff
    reader = PyPDF2.PdfReader(pdf_buffer)
    text = ''
    for page in reader.pages:
        text += page.extract_text()

    # Perform sentiment analysis on the extracted text
    blob = TextBlob(text)
    sentiment = blob.sentiment.polarity

    # Identify key themes from the extracted text
    # First, preprocess the text by tokenising and removing stop words
    tokens = [word for sentence in blob.sentences for word in sentence.words]
    stop_words = set(nltk.corpus.stopwords.words('english'))
    stop_words.update(ignore_words)  # Add the inspections bespoke ignore words to the set of stop words
    tokens = [word for word in tokens if word.lower() not in stop_words]

    # N.B Might need a further preprocessing step to normalise punctuation variations in the above


    # Create a dictionary from the tokenised text
    dictionary = corpora.Dictionary([tokens])

    # Create a corpus from the dictionary and the tokenised text
    corpus = [dictionary.doc2bow(tokens)]

    # Create an LDA model from the corpus
    lda_model = models.LdaModel(corpus, num_topics=3, id2word=dictionary)

    # Get the top 3 topics from the LDA model
    topics = [lda_model.print_topic(topic_num) for topic_num in range(3)]

    return sentiment, topics




# This an updated/extended version of the above
def get_sentiment_and_sentiment_by_theme(pdf_buffer, theme1, theme2, theme3):
    """
    ****In progress****

    Args:


    Returns:

    """

    # Read the PDF stuff
    reader = PyPDF2.PdfReader(pdf_buffer)
    text = ''
    for page in reader.pages:
        text += page.extract_text()

    # Perform sentiment analysis on the extracted text
    blob = TextBlob(text)
    sentiment = blob.sentiment.polarity

    # Identify key themes from the extracted text
    # First, preprocess the text by tokenising and removing stop words
    tokens = [word for sentence in blob.sentences for word in sentence.words]
    stop_words = set(nltk.corpus.stopwords.words('english'))
    tokens = [word for word in tokens if word.lower() not in stop_words]

    # Create a dictionary from the tokenised text
    dictionary = corpora.Dictionary([tokens])

    # Create a corpus from the dictionary and the tokenised text
    corpus = [dictionary.doc2bow(tokens)]


    # Create an LDA model from the corpus with a higher number of topics
    lda_model = models.LdaModel(corpus, num_topics=10, id2word=dictionary)

    # Get all topics from the LDA model
    all_topics = [lda_model.print_topic(topic_num) for topic_num in range(10)]

    # Define a function to calculate similarity between two strings
    def string_similarity(s1, s2):
        vectorizer = CountVectorizer().fit_transform([s1, s2])
        vectors = vectorizer.toarray()
        return cosine_similarity(vectors)[0, 1]

    # Filter topics based on the similarity to the provided theme strings
    filtered_topics = []
    themes = [theme1, theme2, theme3]
    for topic in all_topics:
        for theme in themes:
            if string_similarity(topic, theme) > 0.2:  # Adjust the threshold as needed
                filtered_topics.append(topic)
                break

    return sentiment, filtered_topics

def get_sentiment_category(sentiment):
    """
    Return the sentiment category based on the sentiment value.

    Args:
        sentiment (float): Sentiment value ranging from -1 (most negative) to 1 (most positive).

    Returns:
        str: The sentiment category.
    """

    if sentiment > 0.8:
        return "Sentiment very positive"
    elif 0.4 < sentiment <= 0.8:
        return "Sentiment positive"
    elif -0.4 <= sentiment <= 0.4:
        return "Sentiment neutral"
    elif -0.8 < sentiment <= -0.4:
        return "Sentiment negative"
    else:
        return "Sentiment very negative"


def extract_words(topic_string):
    # Quick fix for when the sentiment weights per topic word not wanted.
    words = re.findall(r'\*"(.*?)"', topic_string)
    return words


def plot_filtered_topics(filtered_topics):
    """
    Note: This only running if using func get_sentiment_and_sentiment_by_theme(pdf_buffer, theme1, theme2, theme3)

    Visualise filtered inspection topics as a bar chart.

    This function takes a list of filtered topics as input and creates a bar chart
    to visualise the weighted words for each topic.

    Args:
        filtered_topics (list): List of filtered topics as strings.

    Returns:
        None
    """

    import matplotlib.pyplot as plt # (intrim impot placement)

    # extract words and their weights from a topic string
    def extract_words_weights(topic_string):
        words_weights = [ww.split('*') for ww in topic_string.split(' + ')]
        return [(float(weight.strip()), word.strip(" '\"")) for weight, word in words_weights]

    # Extract words and their weights from the filtered_topics
    topics_words_weights = [extract_words_weights(topic) for topic in filtered_topics]

    # Create the bar chart for each topic
    for idx, (words_weights, topic) in enumerate(zip(topics_words_weights, filtered_topics), 1):
        words, weights = zip(*words_weights)

        fig, ax = plt.subplots()
        ax.barh(words, weights)
        ax.set_xlabel('Weights')
        ax.set_title(f'Topic {idx}: {topic[:50]}...')
        ax.invert_yaxis()  # Invert y-axis to show higher weights at the top

        plt.show()

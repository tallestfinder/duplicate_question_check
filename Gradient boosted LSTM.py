
# coding: utf-8

# In[1]:


import xgboost


# In[2]:


import pandas as pd
import numpy as np
#import tensorflow as tf
from keras.preprocessing.text import Tokenizer
from keras.preprocessing.sequence import pad_sequences
from keras.layers import Dense, Input, LSTM, Embedding, Dropout
from keras.layers.core import Lambda
from keras.layers.merge import concatenate, add, multiply, subtract
from keras.models import Model
from keras.layers.normalization import BatchNormalization
from keras.callbacks import EarlyStopping, ModelCheckpoint
from keras.layers.noise import GaussianNoise
from sklearn.feature_extraction.text import CountVectorizer
from sklearn.model_selection import StratifiedKFold


# In[3]:


MAX_SEQUENCE_LENGTH = 30
MIN_WORD_OCCURRENCE = 100
REPLACE_WORD = 'dhainchu'
EMBEDDING_DIM = 300
NUM_FOLDS = 30
BATCH_SIZE = 1025


# In[4]:


np.random.seed(0)


# In[5]:


def get_embedding():
    embeddings_index = {}
    f = open('./Data/glove.840B.300d.txt', encoding='utf8')
    for line in f:
        values = line.split()
        word = values[0]
        if len(values) == EMBEDDING_DIM + 1 and word in top_words:
            coeffs = np.asarray(values[1:], dtype='float32')
            embeddings_index[word] = coeffs
    f.close()
    return embeddings_index


# In[6]:


def is_numeric(s):
    return any(i.isdigit() for i in s)


# In[7]:


def prepare(q):
    new_q = []
    surplus_q = []
    numbers_q = []
    new_memento = True
    for w in q.split()[::-1]:
        if w in top_words:
            new_q = [w] + new_q
            new_memento = True
        elif new_memento:
            new_q = ['dhainchu'] + new_q
            new_memento = False
            if is_numeric(w):
                numbers_q = [w] + numbers_q
            else:
                surplus_q = [w] + surplus_q
        else:
            new_memento = True
        if len(new_q) == MAX_SEQUENCE_LENGTH:
            break
    new_q = ' '.join(new_q)
    return new_q, set(surplus_q), set(numbers_q)            


# In[8]:


def extract_features(df):
    q1s = np.array([""] * len(df), dtype=object)
    q2s = np.array([""] * len(df), dtype=object)
    features = np.zeros((len(df), 4))
    for i, (q1, q2) in enumerate(list(zip(df['question1'], df['question2']))):
        q1s[i], surplus1, numbers1 = prepare(q1)
        q2s[i], surplus2, numbers2 = prepare(q2)
        features[i, 0] = len(surplus1.intersection(surplus2))
        features[i, 1] = len(surplus1.union(surplus2))
        features[i, 2] = len(numbers1.intersection(numbers2))
        features[i, 3] = len(numbers1.union(numbers2))
    return q1s, q2s, features


# In[9]:


train = pd.read_csv("./Data/train_cleaned.csv")
test = pd.read_csv("./Data/test_cleaned.csv")


# In[10]:


train['question1'] = train['question1'].fillna("dhainchu")
train['question2'] = train['question2'].fillna("dhainchu")


# In[11]:


print("Creating the vocabulary of words occurred more than", MIN_WORD_OCCURRENCE)
all_questions = pd.Series(train['question1'].tolist() + train['question2'].tolist()).unique()
cv = CountVectorizer(lowercase=False, token_pattern="\S+", min_df=MIN_WORD_OCCURRENCE)
cv.fit(all_questions)
top_words = set(cv.vocabulary_.keys())
top_words.add(REPLACE_WORD)


# In[12]:


embeddings_index = get_embedding()


# In[13]:


print("Words are not found in the embedding:", top_words - embeddings_index.keys())
top_words = embeddings_index.keys()


# In[14]:


print("Train questions are being prepared for LSTM...")
q1s_train, q2s_train, train_q_features = extract_features(train)


# In[15]:


tokenizer = Tokenizer(filters="")
tokenizer.fit_on_texts(np.append(q1s_train, q2s_train))
word_index = tokenizer.word_index


# In[16]:


data_1 = pad_sequences(tokenizer.texts_to_sequences(q1s_train), maxlen=MAX_SEQUENCE_LENGTH)
data_2 = pad_sequences(tokenizer.texts_to_sequences(q2s_train), maxlen=MAX_SEQUENCE_LENGTH)
labels = np.array(train["is_duplicate"])


# In[17]:


nb_words = len(word_index) + 1
embedding_matrix = np.zeros((nb_words, EMBEDDING_DIM))


# In[18]:


for word, i in word_index.items():
    embedding_vector = embeddings_index.get(word)
    if embedding_vector is not None:
        embedding_matrix[i] = embedding_vector


# In[19]:


train_features = pd.read_pickle('./Features/Train/train_features', compression='gzip')
drop_features = ['is_duplicate', 'sentence_length_diff_with_spaces', 'dup_words_diff', 
                 'syllable_count_diff', 'lexicon_count_diff', 'alpha_diff']
train_features.drop(drop_features, axis=1, inplace=True)
features_train = np.hstack((train_q_features, train_features))


# In[20]:


del train_features


# In[21]:


skf = StratifiedKFold(n_splits=NUM_FOLDS, shuffle=True)
model_count = 0


# from keras import optimizers
# nadam = optimizers.Nadam(clipnorm=0.05, lr=0.0001, beta_1=0.9, beta_2=0.999, epsilon=1e-08, schedule_decay=0.004)

# In[22]:


xgseed = np.random.seed(200)


# In[ ]:


for idx_train, idx_val in skf.split(train["is_duplicate"], train["is_duplicate"]):
    print("MODEL:", model_count)
    data_1_train = data_1[idx_train]
    data_2_train = data_2[idx_train]
    labels_train = labels[idx_train]
    f_t = features_train[idx_train]
    
    data_1_val = data_1[idx_val]
    data_2_val = data_2[idx_val]
    labels_val = labels[idx_val]
    f_v = features_train[idx_val]
    
    xgmodel = xgboost.XGBClassifier(gpu_id=0, max_bin=16, tree_method='gpu_hist')
    xg_eval_set = [(f_v, labels_val)]
    xgmodel.fit(f_t, labels_train, eval_metric='logloss', eval_set=xg_eval_set, verbose=True)
    xg_pred_train = xgmodel.predict(f_t)
    xg_pred_val = xgmodel.predict(f_v)
    
    xg_pred_train = xg_pred_train.reshape(len(xg_pred_train), 1)
    xg_pred_val = xg_pred_val.reshape(len(xg_pred_val), 1)
    
    f_train = np.hstack((f_t, xg_pred_train))
    f_val = np.hstack((f_v, xg_pred_val))

    print('Creating embedding layer')
    embedding_layer = Embedding(nb_words,
                                EMBEDDING_DIM,
                                weights=[embedding_matrix],
                                input_length=MAX_SEQUENCE_LENGTH,
                                trainable=False)
    lstm_layer = LSTM(75, recurrent_dropout=0.)

    print('Creating input sequences')
    sequence_1_input = Input(shape=(MAX_SEQUENCE_LENGTH,), dtype="int32")
    print('creating embedding sequences')
    embedded_sequences_1 = embedding_layer(sequence_1_input)
    print('Passing embeddings to lstm')
    x1 = lstm_layer(embedded_sequences_1)    

    sequence_2_input = Input(shape=(MAX_SEQUENCE_LENGTH,), dtype="int32")
    embedded_sequences_2 = embedding_layer(sequence_2_input)
    y1 = lstm_layer(embedded_sequences_2)

    features_input = Input(shape=(f_train.shape[1],), dtype="float32")
    features_dense = BatchNormalization()(features_input)
    features_dense = Dense(200, activation="relu")(features_dense)
    features_dense = Dropout(0.2)(features_dense)

    addition = add([x1, y1])
    minus_y1 = Lambda(lambda x: -x)(y1)
    merged = add([x1, minus_y1])
    merged = multiply([merged, merged])
    merged = concatenate([merged, addition])
    merged = Dropout(0.4)(merged)

    merged = concatenate([merged, features_dense])
    merged = BatchNormalization()(merged)
    merged = GaussianNoise(0.1)(merged)

    merged = Dense(150, activation="relu")(merged)
    merged = Dropout(0.1)(merged)
    merged = BatchNormalization()(merged)

    out = Dense(1, activation="sigmoid")(merged)

    model = Model(inputs=[sequence_1_input, sequence_2_input, features_input], outputs=out)
    model.compile(loss="binary_crossentropy", optimizer='nadam',  metrics=['accuracy'])
    early_stopping = EarlyStopping(monitor="val_loss", patience=5)
    best_model_path = "best_model" + str(model_count) + ".h5"

    print('Model checkpoint layer declaration')
    #with tf.device('/cpu:0'):
        #x = tf.placeholder(tf.float32, shape=(None, 20, 64))
    model_checkpoint = ModelCheckpoint(best_model_path, save_best_only=True, save_weights_only=True)#(x)
    
    print('Fitting')
    #with tf.device('/CPU:0'):
    hist = model.fit([data_1_train, data_2_train, f_train], labels_train,
                         validation_data=([data_1_val, data_2_val, f_val], labels_val),
                         epochs=30, batch_size=BATCH_SIZE, shuffle=True,
                         callbacks=[early_stopping, model_checkpoint], verbose=1) 
    
    
    print("Saving model")
    #with tf.device('/cpu:0'):
        #model.save_weights('model_{}.h5'.format(model_count))
    #export CUDA_VISIBLE_DEVICES=""
    model.load_weights(best_model_path)
    print("Crash test")
    print(model_count, "validation loss:", min(hist.history["val_loss"]))
    
    model_count += 1

import tensorflow as tf
import numpy as np
from argparse import Namespace

meta = Namespace()
meta.batch_size = 8192
meta.embed_dim = 512
meta.window_size = 10
meta.noise_size = 64
meta.learning_rate = 1e-6
meta.training_step = 1000000
meta.interval_save = 100000
meta.interval_print = 100
meta.interval_test = 1500
meta.domain_size = 100000
meta.savefile = './model/model.ckpt'
meta.data_dir = './data'
meta.file_data = '../text8'
meta.label_unknown = '*UNKNOWN*'

class Dataset:

	def __init__(self, meta):
		try:
			print('Loding domain information...')
			self.content = np.load(meta.data_dir + '/content.npy')
			self.content_pd = np.load(meta.data_dir + '/content_pd.npy')
			self.domain = np.load(meta.data_dir + '/domain.npy')
			self.noise_pd = np.load(meta.data_dir + '/noise_pd.npy')
			self.window_size = meta.window_size
		except IOError:
			self.read_data(meta)


	def read_data(self, meta):
		f = open(meta.file_data, 'r', encoding='utf-8')
	
		print('Reading content...')
		
		content_raw = f.readline().lower().split()
		content_raw = np.array(content_raw)

		print('Content length is {}.'.format(len(content_raw)))
		print('Counting domain...')

		domain, content_ind, count = np.unique(content_raw, return_inverse=True, return_counts=True)

		print('Raw domain size is {}.'.format(domain.size))

		if domain.size > meta.domain_size:
			print('Cropping domain...')

			ind_least_words = np.argpartition(count, domain.size - meta.domain_size + 1)[:-meta.domain_size + 1]
			content_raw[np.in1d(content_ind, ind_least_words)] = meta.label_unknown
			
			print('Re-counting domain...')

			domain, content_ind, count = np.unique(content_raw, return_inverse=True, return_counts=True)

		meta.domain_size = len(domain)
		print('Domain size is {}.'.format(len(domain)))

		freq = count / len(domain)
		subsample_ratio = 1. - np.sqrt(1e-5 / freq)
		content_pd = subsample_ratio[content_ind]
		content_pd = content_pd[meta.window_size:-meta.window_size] / np.sum(content_pd[meta.window_size:-meta.window_size])

		noise_count = np.power(count, 2./3.)
		noise_pd = noise_count / np.sum(noise_count)

		self.content = content_ind
		self.content_pd = content_pd
		self.domain = domain
		self.noise_pd = noise_pd
		self.window_size = meta.window_size

		np.save(meta.data_dir + '/content.npy', self.content)
		np.save(meta.data_dir + '/content_pd.npy', self.content_pd)
		np.save(meta.data_dir + '/domain.npy', self.domain)
		np.save(meta.data_dir + '/noise_pd.npy', self.noise_pd)


	def word_index(self, word):
		return np.where(self.domain == word)[0]


	def index_word(self, index):
		return self.domain[index]


	def nearest(self, Q, word, k):
		ind = self.word_index(word)[0]
		embed = np.array([Q[ind]])
		dot = np.sum(np.multiply(np.repeat(embed, Q.shape[0], axis=0), Q), axis=1)
		norm = np.linalg.norm(Q, axis=1) * np.linalg.norm(embed)
		cos = dot / norm
		return self.domain[np.argpartition(-cos, k)[0:k]]


	def analogy(self, Q, a, b, c, k):
		a_ind = self.word_index(a)[0]
		b_ind = self.word_index(b)[0]
		c_ind = self.word_index(c)[0]

		a_embed = Q[a_ind]
		b_embed = Q[b_ind]
		c_embed = Q[c_ind]

		dot = np.matmul(Q, np.array([b_embed - a_embed + c_embed]).T)

		return self.domain[np.argpartition(-np.reshape(dot, [-1]), k)[0:k]]


dataset = Dataset(meta)

def xavier_variable(name, shape):
	if len(shape) == 1:
		inout = np.sum(shape) + 1
	else:
		inout = np.sum(shape)

	init_range = np.sqrt(6.0 / inout)
	initializer = tf.random_uniform_initializer(-init_range, init_range)
	return tf.get_variable(name, shape, initializer=initializer)

Q = xavier_variable('Q', shape=[meta.domain_size, meta.embed_dim])
R = xavier_variable('R', shape=[meta.domain_size, meta.embed_dim])
B = xavier_variable('B', shape=[meta.domain_size])

content = tf.constant(dataset.content, dtype=tf.int32)
content_pd = tf.constant(dataset.content_pd / np.mean(dataset.content_pd), dtype=tf.float32)
np_noise_content = np.repeat(np.arange(meta.domain_size), (dataset.noise_pd * dataset.content.size).astype(np.int32))
noise_content = tf.constant(np_noise_content, dtype=tf.int32)

ind_w_data = tf.random_uniform(shape=[meta.batch_size], minval=meta.window_size, maxval=dataset.content.size, dtype=tf.int32)
ind_c_data = tf.random_uniform(shape=[meta.batch_size], minval=-meta.window_size, maxval=0, dtype=tf.int32)

w_data = tf.nn.embedding_lookup(content, ind_w_data)
c_data = tf.nn.embedding_lookup(content, ind_w_data + ind_c_data)

loss_data = tf.nn.embedding_lookup(content_pd, ind_w_data)

ind_w_noise = tf.random_uniform(shape=[meta.batch_size], minval=0, maxval=np_noise_content.size, dtype=tf.int32)
ind_c_noise = tf.random_uniform(shape=[meta.batch_size], minval=0, maxval=np_noise_content.size, dtype=tf.int32)

w_noise = tf.nn.embedding_lookup(noise_content, ind_w_noise)
c_noise = tf.nn.embedding_lookup(noise_content, ind_c_noise)

q_w_data = tf.nn.embedding_lookup(Q, w_data)
r_c_data = tf.nn.embedding_lookup(R, c_data)
b_c_data = tf.nn.embedding_lookup(B, c_data)

q_w_noise = tf.nn.embedding_lookup(Q, w_noise)
r_c_noise = tf.nn.embedding_lookup(R, c_noise)
b_c_noise = tf.nn.embedding_lookup(B, c_noise)

score_data = tf.reduce_sum(tf.multiply(q_w_data, r_c_data), axis=1) + b_c_data
score_noise = -(tf.reduce_sum(tf.multiply(q_w_noise, r_c_noise), axis=1) + b_c_noise)

loss = -(tf.reduce_sum(tf.multiply(tf.log(tf.sigmoid(score_data)), loss_data)) + tf.reduce_sum(tf.log(tf.sigmoid(score_noise))))
global_step = tf.Variable(0, trainable=False, name='global_step')
train = tf.train.GradientDescentOptimizer(meta.learning_rate).minimize(loss, global_step)

sess = tf.Session()
sess.run(tf.global_variables_initializer())

saver = tf.train.Saver(tf.global_variables())
ckpt = tf.train.get_checkpoint_state('./model')
if ckpt and tf.train.checkpoint_exists(ckpt.model_checkpoint_path):
	saver.restore(sess, ckpt.model_checkpoint_path)
else:
	sess.run(tf.global_variables_initializer())

for _ in range(meta.training_step):
	_, loss_value = sess.run([train, loss], feed_dict={})
	step = sess.run(global_step)

	if step % meta.interval_print == 0:
		print('{}: Loss {:g}'.format(step, loss_value))

	if step % meta.interval_test == 0:
		Q_embed = sess.run(Q, feed_dict={})
		print('one: {}'.format(dataset.nearest(Q_embed, 'one', 5)))
		print('circle: {}'.format(dataset.nearest(Q_embed, 'circle', 5)))
		print('france: {}'.format(dataset.nearest(Q_embed, 'france', 5)))
		print('man to woman is king to: {}'.format(dataset.analogy(Q_embed, 'man', 'woman', 'king', 5)))
		print('rectangle to circle is cube to: {}'.format(dataset.analogy(Q_embed, 'rectangle', 'circle', 'cube', 5)))

	if step % meta.interval_save == 0:
		print('Saving status...')
		saver.save(sess, meta.savefile, global_step=global_step)

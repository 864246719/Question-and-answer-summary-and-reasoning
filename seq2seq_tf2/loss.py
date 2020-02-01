import tensorflow as tf


loss_object = tf.keras.losses.SparseCategoricalCrossentropy(from_logits=True, reduction='none')


def loss_function(real, pred, padding_mask, attn_dists, cov_loss_wt, use_coverage):
    if use_coverage:
        loss = pgn_log_loss_function(real, pred, padding_mask) + cov_loss_wt * _coverage_loss(attn_dists, padding_mask)
        return loss
    else:
        return seq2seq_loss_function(real, pred)


def seq2seq_loss_function(real, pred):
    """
    跑seq2seq时用的Loss
    :param real: shape=(16, 50)
    :param pred: shape=(16, 50, 30000)
    :return:
    """
    mask = tf.math.logical_not(tf.math.equal(real, 1))
    dec_lens = tf.reduce_sum(tf.cast(mask, dtype=tf.float32), axis=-1)
    loss_ = loss_object(real, pred)
    mask = tf.cast(mask, dtype=loss_.dtype)
    loss_ *= mask
    # we have to make sure no empty abstract is being used otherwise dec_lens may contain null values
    # loss_ = tf.reduce_sum(loss_, axis=-1) / dec_lens
    return tf.reduce_mean(loss_)


def pgn_log_loss_function(real, final_dists, padding_mask):
    # Calculate the loss per step
    # This is fiddly; we use tf.gather_nd to pick out the probabilities of the gold target words
    loss_per_step = []  # will be list length max_dec_steps containing shape (batch_size)
    batch_nums = tf.range(0, limit=real.shape[0])  # shape (batch_size)
    # print('final_dists is ', final_dists)
    for dec_step, dist in enumerate(final_dists):
        # The indices of the target words. shape (batch_size)
        # print('real is ', real)
        targets = real[:, dec_step]
        # print('targets is ', targets)
        indices = tf.stack((batch_nums, targets), axis=1)  # shape (batch_size, 2)
        # print('indices is ', indices)
        # print('dist is', dist)
        gold_probs = tf.gather_nd(dist, indices)  # shape (batch_size). prob of correct words on this step
        # print('gold_probs is ', gold_probs)
        losses = -tf.math.log(gold_probs)
        # print('losses is ', losses)
        loss_per_step.append(losses)
    # print(loss_per_step)
    # Apply dec_padding_mask and get loss
    _loss = _mask_and_avg(loss_per_step, padding_mask)
    # print(_loss)
    return _loss


def _mask_and_avg(values, padding_mask):
    """Applies mask to values then returns overall average (a scalar)
    Args:
      values: a list length max_dec_steps containing arrays shape (batch_size).
      padding_mask: tensor shape (batch_size, max_dec_steps) containing 1s and 0s.
    Returns:
      a scalar
    """
    # padding_mask is Tensor("Cast_2:0", shape=(64, 400), dtype=float32)
    # print('values is ', values)
    # print('padding_mask is ', padding_mask)
    padding_mask = tf.cast(padding_mask, dtype=values[0].dtype)
    dec_lens = tf.reduce_sum(padding_mask, axis=1)  # shape batch_size. float32
    values_per_step = [v * padding_mask[:, dec_step] for dec_step, v in enumerate(values)]
    values_per_ex = sum(values_per_step) / dec_lens  # shape (batch_size); normalized value for each batch member
    return tf.reduce_mean(values_per_ex)  # overall average


def _coverage_loss(attn_dists, padding_mask):
    """Calculates the coverage loss from the attention distributions.
    Args:
      attn_dists: The attention distributions for each decoder timestep.
      A list length max_dec_steps containing shape (batch_size, attn_length)
      padding_mask: shape (batch_size, max_dec_steps).
    Returns:
      coverage_loss: scalar
    """
    coverage = tf.zeros_like(attn_dists[0])  # shape (batch_size, attn_length). Initial coverage is zero.
    # Coverage loss per decoder timestep. Will be list length max_dec_steps containing shape (batch_size).
    covlosses = []
    for a in attn_dists:
        covloss = tf.reduce_sum(tf.minimum(a, coverage), [1])  # calculate the coverage loss for this step
        covlosses.append(covloss)
        coverage += a  # update the coverage vector
    coverage_loss = _mask_and_avg(covlosses, padding_mask)
    return coverage_loss
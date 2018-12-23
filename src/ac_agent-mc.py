# -*- coding: utf-8 -*-
import sys
import os
import shutil
import numpy as np
from collections import namedtuple
from itertools import count
import torch
import torch.nn as nn
import torch.optim as optim
import torch.nn.functional as F
from collections import deque
from engine import TetrisEngine

width, height = 10, 8  # standard tetris friends rules
engine = TetrisEngine(width, height, enable_KO=False)
eps = 10.**-8

use_cuda = torch.cuda.is_available()
if use_cuda:
    print("....Using Gpu...")
FloatTensor = torch.cuda.FloatTensor if use_cuda else torch.FloatTensor
LongTensor = torch.cuda.LongTensor if use_cuda else torch.LongTensor
ByteTensor = torch.cuda.ByteTensor if use_cuda else torch.ByteTensor

Transition = namedtuple('Transition',
                        ('state', 'action', 'shape', 'anchor', 'board', 'reward'))


class AC(nn.Module):

    def __init__(self):
        super(AC, self).__init__()
        self.cnn = CNN_lay()
        self.lin1 = nn.Linear(640, 64)
        self.Q_lin = nn.Linear(2*64, 1)
        self.V_lin = nn.Linear(64, 1)

    def forward(self, x, placement):
        batch, _, _, _ = x.shape
#         
        base = torch.ones([batch, 1, width, 20-height]).type(FloatTensor)
        base.requires_grad_(False)
        x = torch.cat([x, base], dim=-1)
        placement = torch.cat([placement, base], dim=-1)
#         
        x = self.cnn(x)
        x = x.view(batch, -1)
        placement = self.cnn(placement)
        placement = placement.view(batch, -1)

        x = F.relu(self.lin1(x))
        placement = F.relu(self.lin1(placement))

        Q = self.Q_lin(torch.cat([x, placement], dim=-1))
        V = self.V_lin(x)
        return Q, V


class CNN_lay(nn.Module):

    def __init__(self):
        super(CNN_lay, self).__init__()
        self.conv1 = nn.Conv2d(1, 16, kernel_size=5, stride=1, padding=2)
        self.bn1 = nn.BatchNorm2d(16)
        self.conv2 = nn.Conv2d(16, 32, kernel_size=3, stride=1, padding=1)
        self.bn2 = nn.BatchNorm2d(32)
        self.conv_collapse = nn.Conv2d(32, 64, kernel_size=(1, 20), stride=1)
        self.bn4 = nn.BatchNorm2d(64)
        self.conv5 = nn.Conv2d(64, 64, kernel_size=(3, 1), stride=1, padding=(1, 0))
        self.bn5 = nn.BatchNorm2d(64)

    def forward(self, x):
        x = F.relu(self.bn1(self.conv1(x)))
        x = F.relu(self.bn2(self.conv2(x)))
        x = F.relu(self.bn4(self.conv_collapse(x)))
        x = F.relu(self.bn5(self.conv5(x)))
        return x


GAMMA = 0.99

model = AC()
print(model)

if use_cuda:
    model.cuda()
critic_params = [m for m in model.cnn.parameters()] + [m for m in model.lin1.parameters()] \
                    + [m for m in model.V_lin.parameters()]
actor_params = [m for m in model.cnn.parameters()] + [m for m in model.lin1.parameters()] \
                    + [m for m in model.Q_lin.parameters()]
critic_opt = optim.Adam(critic_params, lr=.001)
actor_opt = optim.Adam(actor_params, lr=.001)


def entropy(act_prob):
    assert len(act_prob.shape) == 1
    entropy = torch.sum(-torch.log(act_prob + eps) * act_prob)
    return entropy


def discount_rewards(rewards):
    rewards = np.array(rewards, dtype=np.float)
    discounted_rewards = np.zeros_like(rewards)
    running_add = 0
    for t in reversed(range(0, len(rewards))):
        if rewards[t] != 0:
            running_add = 0
        running_add = running_add * GAMMA + rewards[t]
        discounted_rewards[t] = running_add
    rewards = discounted_rewards
#     rewards = (rewards - rewards.mean()) / (rewards.std())
    return rewards


def get_action_probability(model, state, act_pairs):
    placements = torch.cat([FloatTensor(v)[None, None, :, :] for k, v in act_pairs], dim=0)
    states = FloatTensor(state)[None, None, :, :].repeat(len(act_pairs), 1, 1, 1)
    act_score, V = model(states, placements)
    act_score = act_score.flatten()
    assert act_score.shape == (len(act_pairs),)
    act_prob = F.softmax(act_score, dim=0)
    return act_prob, V[0, :]


def save_checkpoint(state, is_best, filename, best_name):
    torch.save(state, filename)
    if is_best:
        shutil.copyfile(filename, best_name)


def load_checkpoint(filename):
    checkpoint = torch.load(filename)
    model.load_state_dict(checkpoint['state_dict'])
    return checkpoint['epoch'], checkpoint['best_score']


if __name__ == '__main__':
    # Check if user specified to resume from a checkpoint
    start_epoch = 0
    best_score = float('-inf')
    if len(sys.argv) > 1 and sys.argv[1] == 'resume':
        if len(sys.argv) > 2:
            CHECKPOINT_FILE = sys.argv[2]
        if os.path.isfile(CHECKPOINT_FILE):
            print("=> loading checkpoint '{}'".format(CHECKPOINT_FILE))
            start_epoch, best_score = load_checkpoint(CHECKPOINT_FILE)
            print("=> loaded checkpoint '{}' (epoch {})"
                  .format(CHECKPOINT_FILE, start_epoch))
        else:
            print("=> no checkpoint found at '{}'".format(CHECKPOINT_FILE))

    ######################################################################
    score_q = deque(maxlen=100)
    model.train()
    f = open('ac_easy.out', 'w+')
    for i_episode in count(start_epoch):
        # Initialize the environment and state
        
        state = engine.clear()
        state,_,_,_ = engine.step(6)
        score = 0
        rewards = []
        entropy_loss = 0
        act_prob_list = []
        V_list = []
        for t in count():
            # Select and perform an action
            action_final_location_map = engine.get_valid_final_states(engine.shape, engine.anchor, engine.board)
            act_pairs = [(k, v[2]) for k, v in action_final_location_map.items()]

            act_prob, V = get_action_probability(model, state, act_pairs)
            act_idx = int(np.random.choice(len(act_prob), 1, p=act_prob.cpu().detach().numpy()))
            act_prob_list.append(act_prob[act_idx].unsqueeze(0))
            V_list.append(V.unsqueeze(0))
            entropy_loss += -entropy(act_prob)
            act, placement = act_pairs[act_idx]

            # Observations
            state, reward, done, cleared_lines = engine.step_to_final(act)
            # for training purpose
            reward = cleared_lines**2 if not done else -100
            # Accumulate reward
            score += cleared_lines
            rewards.append(reward)
            if done:
                R = sum(rewards)
                discounted_rewards = [0]*len(rewards)
                discounted_rewards[-1] = R
                discounted_rewards = FloatTensor(discount_rewards(discounted_rewards))

                act_probs = torch.cat(act_prob_list, dim=0)
                V = torch.cat(V_list, dim=0).flatten()
                critic_opt.zero_grad()
                critic_loss = F.smooth_l1_loss(V, discounted_rewards)
                critic_loss.backward(retain_graph=True)
                for param in critic_params:
                    param.grad.data.clamp_(-1, 1)
                critic_opt.step()

                actor_opt.zero_grad()
                r = FloatTensor(rewards)
                next_V = torch.zeros_like(V)
                next_V[:-1] = V[1:]
                adv = (r+GAMMA*next_V-V).detach()
                loss = torch.sum(-torch.log(act_probs + eps) * adv) + 0.01*entropy_loss
                loss.backward()
                for param in actor_params:
                    param.grad.data.clamp_(-1, 1)
                actor_opt.step()
                score_q.append(score)
                log = 'epoch {0} score {1} rewards {2} score_mean {3}'.format(
                        i_episode,
                        '%.2f' % score, '%.2f' % R, '%.2f' % np.mean(score_q)
                        )
                f.write(log + '\n')
                # Train model
                if i_episode % 10 == 0:
                    print(log)
                    if loss:
                        print('actor loss : {:.2f} critic loss : {:.2f}'.format(loss, critic_loss))
                # Checkpoint
                if i_episode % 100 == 0:
                    is_best = True if score > best_score else False
                    save_checkpoint({
                        'epoch': i_episode,
                        'state_dict': model.state_dict(),
                        'best_score': best_score,
                        }, is_best, filename='ac_easy.pth.tar', best_name='ac_easy_best.pth.tar')
                    best_score = score
                break

    f.close()
    print('Complete')

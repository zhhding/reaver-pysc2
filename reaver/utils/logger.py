import gin
import sys
import time
import numpy as np
from collections import deque


class Logger:
    def on_step(self, step): ...

    def on_update(self, step, loss_terms, grads_norm, returns, adv, next_value): ...


@gin.configurable
class AgentLogger(Logger):
    def __init__(self, agent, act_spec, n_updates=100, n_detailed=10, verbosity=3):
        # TODO remove dependency on agent
        self.agent = agent
        self.verbosity = verbosity
        self.n_updates = n_updates
        self.n_detailed = n_detailed
        self.can_v4 = not act_spec.spaces[0].is_continuous()

        self.env_eps = [0] * agent.n_envs
        self.env_rews = [0] * agent.n_envs
        self.n_eps = max(10, agent.n_envs)
        self.tot_rews = deque([], maxlen=self.n_eps)

    def on_step(self, step):
        t = step % self.agent.traj_len
        self.env_rews += self.agent.rewards[t]
        for i in range(self.agent.n_envs):
            if self.agent.dones[t, i]:
                self.tot_rews.append(self.env_rews[i])
                self.env_rews[i] = 0.
                self.env_eps[i] += 1

    def on_update(self, step, loss_terms, grads_norm, returns, adv, next_value):
        if self.verbosity < 1:
            return

        update_step = (step + 1) // self.agent.traj_len
        if update_step > 1 and update_step % self.n_updates:
            return

        loss_terms = np.array(loss_terms).round(5)
        np.set_printoptions(suppress=True, precision=3)

        print("######################################################")
        runtime = max(1, int(time.time() - self.agent.start_time))
        frames = (step + 1) * self.agent.n_envs

        print("Runner Stats:")
        print("Time    ", runtime)
        print("Eps     ", int(np.sum(self.env_eps)))
        print("Frames  ", frames)
        print("Steps   ", step + 1)
        print("Updates ", update_step)
        print("FPS     ", frames // runtime)

        tot_rews = self.tot_rews if len(self.tot_rews) > 0 else [0]
        rews = [np.mean(tot_rews), np.std(tot_rews), np.min(tot_rews), np.max(tot_rews)]
        print()
        print("Total Rewards For Last %d Eps:" % self.n_eps)
        print("Mean %.3f" % rews[0])
        print("Std  %.3f" % rews[1])
        print("Min  %.3f" % rews[2])
        print("Max  %.3f" % rews[3])
        # TODO split console and tf summaries into separate loggers
        self.agent.sess_mgr.add_summaries(['Mean', 'Std', 'Min', 'Max'], rews, 'Rewards', update_step)

        if self.verbosity < 2:
            return

        print()
        print("Losses For Last Update:")
        print("Policy loss  ", loss_terms[0])
        print("Value loss   ", loss_terms[1])
        print("Entropy loss ", loss_terms[2])
        print("Grads norm   ", grads_norm)
        self.agent.sess_mgr.add_summaries(['Policy', 'Value', 'Entropy'], loss_terms, 'Losses', update_step)
        self.agent.sess_mgr.add_summary('Grads', grads_norm, 'Losses', update_step)

        if self.verbosity < 3:
            return

        np.set_printoptions(suppress=True, precision=2)
        n_steps = min(self.n_detailed, self.agent.traj_len)

        print()
        print("First Env For Last %d Steps:" % n_steps)
        print("Dones      ", self.agent.dones[-n_steps:, 0].flatten().astype(int))
        print("Rewards    ", self.agent.rewards[-n_steps:, 0].flatten())
        print("Values     ", self.agent.values[-n_steps:, 0].flatten(), round(next_value[0], 3))
        print("Returns    ", returns[-n_steps:, 0].flatten())
        print("Advs       ", adv[-n_steps:, 0].flatten())

        if self.verbosity >= 4 and self.can_v4:
            logits = self.agent.sess_mgr.run(self.agent.policy.logits[0], self.agent.model.inputs,
                            [o[-n_steps:, 0] for o in self.agent.obs])
            action_ids = self.agent.acts[0][-n_steps:, 0].flatten()

            print("Action ids ", action_ids)
            print("Act logits ", logits[np.arange(n_steps), action_ids])

        if self.verbosity >= 5 and self.can_v4:
            print()
            print("Note: action ids listed are not equivalent to pysc2")
            for t in range(n_steps - 1, -1, -1):
                trv = n_steps - t
                avail = np.argwhere(self.agent.obs[2][-trv, 0]).flatten()
                avail_logits = logits[t, avail]
                avail_sorted = np.argsort(avail_logits)
                print("Step", -trv + 1)
                print("Actions   ", self.agent.obs[2][-trv, 0].sum())
                print("Action ids", avail[avail_sorted[:3]], "..." * 3, avail[avail_sorted[-5:]])
                print("Logits    ", avail_logits[avail_sorted[:3]], "...", avail_logits[avail_sorted[-5:]])
            print("######################################################")

        sys.stdout.flush()

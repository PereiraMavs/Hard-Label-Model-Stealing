

from __future__ import print_function
import argparse
import os
import random
import torch
import torch.nn as nn
import torch.nn.parallel
import torch.backends.cudnn as cudnn
import torch.optim as optim
import torch.utils.data
import torchvision.datasets as dset
import torchvision.transforms as transforms
import torch.nn.functional as F
from tensorboardX import SummaryWriter
import numpy as np
from dcgan_model import Generator, Discriminator
from models import ResNet18, AlexNet_half, AlexNet_half_wo_BN
#from alexnet import AlexNet
#import tensorflow as tf
import torchvision
from torch.utils.data import Dataset
from auto_augment import AutoAugment
import pandas as pd

from PIL import Image
from models import *
import pickle

writer = SummaryWriter()

def find_epoch_num(ep):
    if ep>=0 and ep<35:
        return 35
    elif ep>=35 and ep<50:
        return 50
    elif ep>=50 and ep<85:
        return 85
    elif ep>=85 and ep<100:
        return 100
    elif ep>=100 and ep<135:
        return 135
    elif ep>=135 and ep<150:
        return 150
    elif ep>=150 and ep<175:
        return 175
    else:
        return 200


def filter_indices(trainset):
    index_list = []
    print("indices = ", classes_indices)
    for i in range(len(trainset)):
        if trainset[i][1] in classes_indices:
           index_list.append(i)
    return index_list

class GeneratedDataset(Dataset):

    def __init__(self, data, targets, transform=None):
        self.data = data
        self.targets = targets
        self.transform = transform

    def __len__(self):
        return len(self.data)

    def __getitem__(self, idx):
        if torch.is_tensor(idx):
            idx = idx.tolist()

        return self.data[idx], self.targets[idx]

class SyntheticDataset(Dataset):
    """Synthetic dataset."""

    def __init__(self, csv_file, root_dir, transform=None, length=50000, grey=False):
        self.csv_file = pd.read_csv(csv_file)
        self.root_dir = root_dir
        self.transform = transform
        self.length = length
        self.grey = grey

    def __len__(self):
        return self.length

    def __getitem__(self, idx):
        if torch.is_tensor(idx):
            idx = idx.tolist()
        dummy_label = 0
        img_name = os.path.join(self.root_dir, self.csv_file.iloc[idx]['filename'])
        img = Image.open(img_name)

        if self.transform:
            img = self.transform(img)
        if self.grey==True:
            img[0] = img[1]
            img[2] = img[1]
            return img, dummy_label
        else:
            return img, dummy_label

def get_model_accuracy(net, test_loader_):
    net.eval()
    correct = 0
    total = 0
    with torch.no_grad():
        for batch_idx, (inputs, targets) in enumerate(test_loader_):
            inputs, targets = inputs.to(device), targets.to(device)
            outputs = net(inputs)
            _, predicted = outputs.max(1)
            total += targets.size(0)
            correct += predicted.eq(targets).sum().item()

            #progress_bar(batch_idx, len(testloader), 'Loss: %.3f | Acc: %.3f%% (%d/%d)'
            #             % (test_loss/(batch_idx+1), 100.*correct/total, correct, total))

    acc = 100.*correct/total
    return acc

def adjust_momentum(epoch, momentum, max_epochs):
    momentum_inv = (1 - momentum)
    eta_min = 0
    momentum_inv = eta_min + (momentum_inv - eta_min) * (
                1 + math.cos(math.pi * epoch / max_epochs)) / 2
    momentum = 1 - momentum_inv
    return momentum 




if __name__ == '__main__':    

    parser = argparse.ArgumentParser()
    parser.add_argument('--dataroot', required=True, help='path to dataset')
    parser.add_argument('--workers', type=int, help='number of data loading workers', default=2)
    parser.add_argument('--batchSize', type=int, default=64, help='input batch size')
    parser.add_argument('--imageSize', type=int, default=64, help='the height / width of the input image to network')
    parser.add_argument('--nz', type=int, default=100, help='size of the latent z vector')
    parser.add_argument('--ngf', type=int, default=64)
    parser.add_argument('--ndf', type=int, default=64)
    parser.add_argument('--niter', type=int, default=25, help='number of epochs to train for')
    parser.add_argument('--lr', type=float, default=0.0002, help='learning rate, default=0.0002')
    parser.add_argument('--beta1', type=float, default=0.5, help='beta1 for adam. default=0.5')
    parser.add_argument('--cuda', action='store_true', help='enables cuda')
    parser.add_argument('--use_teacher', action='store_true', help='use gradients from teacher')
    parser.add_argument('--ngpu', type=int, default=1, help='number of GPUs to use')
    parser.add_argument('--netG', default='', help="path to netG (to continue training)")
    parser.add_argument('--netD', default='', help="path to netD (to continue training)")
    parser.add_argument('--outf', default='.', help='folder to output images and model checkpoints')
    parser.add_argument('--manualSeed', type=int, help='manual seed')
    parser.add_argument('--disable_dis', action='store_true', help='disable discriminator')
    parser.add_argument('--dataset', type=str, default='svhn', help='Dataset used to train GAN')
    parser.add_argument('--student_path', type=str, default='', help='Student model as proxy for teacher')
    parser.add_argument('--teacher_path', type=str, default='', help='Teacher model')
    parser.add_argument('--network', type=str, default='resnet', help='resnet or alexnet')
    parser.add_argument('--diverse', action='store_true', help='train gan with diverse data')
    parser.add_argument('--warmup', action='store_true', help='use warmup ')
    parser.add_argument('--student_lr', type=float, default=0.01, help='student learning rate, default=0.01')
    parser.add_argument('--auto-augment', action='store_true', help='use auto augment')
    parser.add_argument('--name', type=str, default='', help='name of best student model')
    parser.add_argument('--c_l', type=float, default=0, help='c_l')
    parser.add_argument('--d_l', type=float, default=500, help='d_l')
    parser.add_argument('--eps', type=float, default=0.001, help='eps')
    parser.add_argument('--use_ce_loss', action='store_true', help='use ce loss')
    parser.add_argument('--use_wa_student_ce_loss', action='store_true', help='use WA ce loss')
    parser.add_argument('--use_wa_student_div_loss', action='store_true', help='use WA student for div loss')
    parser.add_argument('--use_adversarial_z', action='store_true', help='use adv z updates')
    parser.add_argument('--use_adversarial_z_adaptive', action='store_true', help='use adaptive adv z updates')
    parser.add_argument('--negative_grad', action='store_true', help='use -ve sign for adv z updates')
    parser.add_argument('--use_KL_wa_loss', action='store_true', help='use KL div loss between two student models')
    parser.add_argument('--ce_l', type=float, default=5, help='ce_l')
    parser.add_argument('--k_l', type=float, default=0.5, help='k_l')
    parser.add_argument('--use_proxy_data', action='store_true', help='use proxy data from training student')
    parser.add_argument('--use_proxy_frequency', type=int, default=10, help='use proxy data from training student')
    parser.add_argument('--proxy_ds_name', type=str, default='40_class', help='Dataset used to train GAN')
    parser.add_argument('--val_data_dcgan', default='', type=str, help='name of dcgan val data')
    parser.add_argument('--val_data_degan', default='', type=str, help='name of degan val data')
    parser.add_argument('--temp', type=float, default=1, help='temp')

    parser.add_argument('--true_dataset', default='cifar10', type=str, help='true dataset')
    parser.add_argument('--num_classes', default=10, type=int, help='num of classes of teacher model')
    parser.add_argument('--synthetic_dir', default='', type=str, help='path of synthetic dir')
    parser.add_argument('--total_synth_samples', default=50000, type=int, help='num of synthetic samples')
    parser.add_argument('--grey_scale', action='store_true', help="grey scale images to train student")
    parser.add_argument('--wo_batch_norm', action='store_true', help="train student removing batch norm layers")

    opt = parser.parse_args()
    print(opt)

    if opt.val_data_dcgan!='':
        with open(opt.val_data_dcgan,'rb') as f:
            val_data_dcgan = pickle.load(f)
        val_dcgan_loader = torch.utils.data.DataLoader(
                    val_data_dcgan, batch_size=128, shuffle=True, num_workers=2)

    if opt.val_data_degan!='':
        with open(opt.val_data_degan,'rb') as f:
            val_data_degan = pickle.load(f)
        val_degan_loader = torch.utils.data.DataLoader(
                    val_data_degan, batch_size=128, shuffle=True, num_workers=2)

    try:
        os.makedirs(opt.outf)
    except OSError:
        pass

    if opt.manualSeed is None:
        opt.manualSeed = random.randint(1, 10000)
    print("Random Seed: ", opt.manualSeed)
    random.seed(opt.manualSeed)
    torch.manual_seed(opt.manualSeed)

    cudnn.benchmark = True

    if torch.cuda.is_available() and not opt.cuda:
        print("WARNING: You have a CUDA device, so you should probably run with --cuda")

    transform_train = transforms.Compose([
        transforms.RandomCrop(32, padding=4),
        transforms.RandomHorizontalFlip(),
        transforms.ToTensor(),
        transforms.Normalize((0.5, 0.5, 0.5), (0.5, 0.5, 0.5)),
    ])

    if opt.auto_augment:
        pil_transform = transforms.Compose([
            transforms.ToPILImage(),
            AutoAugment(),
            transforms.ToTensor(),
            transforms.Normalize((0.5, 0.5, 0.5),
                             (0.5, 0.5, 0.5))])
    if opt.dataset=='svhn':
        dataset =  torchvision.datasets.SVHN(root=opt.dataroot, split='train', download=True, transform=transform_train)
    elif opt.dataset=='cifar100':
        trainset =  torchvision.datasets.CIFAR100(
                    root=opt.dataroot, train=True, download=True, transform=transform_train)

        print(trainset.class_to_idx)
        id_to_class_mapping = {}
        for cl, idx in trainset.class_to_idx.items():
            id_to_class_mapping[idx] = cl
        print(id_to_class_mapping)

        if opt.proxy_ds_name == '40_class':
            classes_set = {'orchid', 'poppy', 'rose', 'sunflower', 'tulip',
            'bottle', 'bowl', 'can', 'cup', 'plate',
            'apple', 'mushroom', 'orange', 'pear', 'sweet_pepper',
            'clock', 'keyboard', 'lamp', 'telephone', 'television',
            'bed', 'chair', 'couch', 'table', 'wardrobe',
            'maple_tree', 'oak_tree', 'palm_tree', 'pine_tree', 'willow_tree',
            'bridge', 'castle', 'house', 'road', 'skyscraper',
            'cloud', 'forest', 'mountain', 'plain', 'sea'}
        elif opt.proxy_ds_name == '6_class':
            classes_set = {'road', 'cloud', 'forest', 'mountain', 'plain', 'sea'}
        else:
            classes_set = {'plate', 'rose', 'castle', 'keyboard', 'house', 'forest', 'road', 'television', 'bottle', 'wardrobe'}

        classes_indices = []
        for k in classes_set:
            classes_indices.append(trainset.class_to_idx[k])
        print(classes_indices)

        index_list = filter_indices(trainset)

        dataset = torch.utils.data.Subset(trainset, index_list)
        print(len(dataset))
    
    elif opt.dataset=='cifar10':
        print("cifar-10 dataset ")
        dataset =  torchvision.datasets.CIFAR10(
                root=opt.dataroot, train=True, download=True, transform=transform_train)

    elif opt.dataset=='synthetic':
        arr = os.listdir(opt.synthetic_dir)
        synthetic_data = pd.DataFrame(data=arr, columns=['filename'])
        csv_filename = 'synthetic_data.csv'
        synthetic_data.to_csv(csv_filename)
        print(csv_filename)
        dir_name = opt.synthetic_dir
        dataset = SyntheticDataset(csv_file=csv_filename, root_dir=dir_name, transform=transform_train, length=int(opt.total_synth_samples), grey=opt.grey_scale)



    """
    dataset = dset.CIFAR100(root=opt.dataroot, download=True,
                           transform=transforms.Compose([
                               transforms.Scale(opt.imageSize),
                               transforms.ToTensor(),
                               transforms.Normalize((0.5, 0.5, 0.5), (0.5, 0.5, 0.5)),
                           ]))
    """

    nc=3

    assert dataset

    dataloader = torch.utils.data.DataLoader(dataset, batch_size=opt.batchSize,
                                             shuffle=True, num_workers=int(opt.workers))


    device = torch.device("cuda:0" if opt.cuda else "cpu")
    ngpu = int(opt.ngpu)
    nz = int(opt.nz)
    ngf = int(opt.ngf)
    ndf = int(opt.ndf)

    # custom weights initialization called on netG and netD
    def weights_init(m):
        classname = m.__class__.__name__
        if classname.find('Conv') != -1:
            m.weight.data.normal_(0.0, 0.02)
        elif classname.find('BatchNorm') != -1:
            m.weight.data.normal_(1.0, 0.02)
            m.bias.data.fill_(0)

    netG = Generator(ngpu).to(device)
    #netG = torch.nn.DataParallel(netG)
    netG.apply(weights_init)
    if opt.netG != '':
        netG.load_state_dict(torch.load(opt.netG))
    print(netG)

    if opt.network == 'resnet':
        teacher_net = ResNet18(opt.num_classes)
    else:
        teacher_net = AlexNet()
    teacher_net = teacher_net.to(device)
    teacher_net = torch.nn.DataParallel(teacher_net)
    state = {
            'net': teacher_net.state_dict(),
            'acc': 90,
            'epoch': 200,
            }
    state = torch.load(str(opt.teacher_path))
    print("Teacher Acc : ", state['acc'])
    teacher_net.load_state_dict(state['net'])
    teacher_net.eval()

    if opt.use_teacher==True:
        netC = AlexNet()
        netC = netC.to(device)
        netC = torch.nn.DataParallel(netC)
    elif opt.network=='resnet':
        netC = ResNet18(opt.num_classes)
        netC = netC.to(device)
    else:
        if opt.wo_batch_norm==True:
            netC = AlexNet_half_wo_BN()
        else:
            netC = AlexNet_half()
        netC = netC.to(device)
    #netC = torch.nn.DataParallel(netC)
    state = {
            'net': netC.state_dict(),
            'acc': 90,
            'epoch': 200,
            }
    state = torch.load(str(opt.student_path))
    print(state['acc'])
    netC.load_state_dict(state['net']) 
    netC.eval()
            
    target_arr = torch.zeros((len(dataset)))
    images = torch.zeros((len(dataset), 3, 32, 32))
    for idx in range(0, len(dataset)):
        images[idx] = dataset[idx][0]
        
    for i in range(len(dataset)):
        inputs = torch.reshape(images[i], (1,3,32,32))
        teacher_outputs = teacher_net(inputs)
        teacher_outputs = teacher_outputs.detach()
        _, teacher_predicted = teacher_outputs.max(1)
        target_arr[i] = teacher_predicted.item()

    gen_set = GeneratedDataset(data = images, targets = target_arr, transform=transform_train)

    trainloader_proxy = torch.utils.data.DataLoader(
            gen_set, batch_size=opt.batchSize, shuffle=True, num_workers=2)



    if not opt.disable_dis:
        netD = Discriminator(ngpu).to(device)
        netD.apply(weights_init)
        if opt.netD != '':
            netD.load_state_dict(torch.load(opt.netD))
        print(netD)

    criterion = nn.BCELoss()
    criterion_sum = nn.BCELoss(reduction = 'sum')

    fixed_noise = torch.randn(opt.batchSize, nz, 1, 1, device=device)
    real_label = 1
    fake_label = 0

    # setup optimizer
    if not opt.disable_dis:
        optimizerD = optim.Adam(netD.parameters(), lr=opt.lr, betas=(opt.beta1, 0.999))
    optimizerG = optim.Adam(netG.parameters(), lr=opt.lr, betas=(opt.beta1, 0.999))
    threshold = []
    # Load Cifar-10 test data
    transform_test = transforms.Compose([
        transforms.ToTensor(),
        transforms.Normalize((0.5, 0.5, 0.5), (0.5, 0.5, 0.5)),
    ])
    if opt.true_dataset=='cifar10':
        testset = torchvision.datasets.CIFAR10(
                root='./data/', train=False, download=True, transform=transform_test)
    elif opt.true_dataset=='cifar100':
        testset = torchvision.datasets.CIFAR100(
                root='./data/', train=False, download=True, transform=transform_test)
    testloader = torch.utils.data.DataLoader(
                testset, batch_size=100, shuffle=False, num_workers=2)

    print("Student Start Acc = ", get_model_accuracy(netC, testloader))

    
    criterion_student = nn.CrossEntropyLoss()
    #criterion_kl = nn.KLDivLoss(size_average=False)
    criterion_student_sum = nn.CrossEntropyLoss(reduction='sum')
    optimizer_student = optim.SGD(netC.parameters(), lr=opt.student_lr,
                        momentum=0.9, weight_decay=5e-4)
    scheduler_student = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer_student, T_max = opt.niter)
    inital_lr = 0.001
    best_acc = 0
    best_dcgan_acc = 0
    best_degan_acc = 0
    best_agg = 0
    if opt.diverse==True:
        num_samples = 50000
        gen_batch_size = 10
        diverse_images = torch.zeros((num_samples,3,32,32))
        netG.eval()
        for idx in range(int(num_samples/gen_batch_size)):
            noise_test = torch.randn(gen_batch_size, nz, 1, 1, device=device)
            imgs = netG(noise_test)
            diverse_images[(idx*gen_batch_size) : (idx*gen_batch_size + gen_batch_size)] = imgs.detach().cpu()
        
        target_arr = torch.zeros((len(diverse_images)))
        for i in range(len(diverse_images)):
            inputs = torch.reshape(diverse_images[i], (1,3,32,32))
            teacher_outputs = teacher_net(inputs)
            teacher_outputs = teacher_outputs.detach()
            _, teacher_predicted = teacher_outputs.max(1)
            target_arr[i] = teacher_predicted.item()

        gen_set = GeneratedDataset(data = diverse_images, targets = target_arr, transform=transform_train)

        trainloader1 = torch.utils.data.DataLoader(
            gen_set, batch_size=opt.batchSize, shuffle=True, num_workers=2)
    
    train_accs = []
    dcgan_val_accs = []
    degan_val_accs = []
    agg_accs = []
    test_accs = []

    fixed_tau_list = [0,0.5,0.9,0.99,0.999,0.9995,0.9998]
    fixed_exp_avgs = []
    cosine_tau_list = [0,0.5,0.9,0.99,0.999,0.9995,0.9998]
    cosine_exp_avgs = []
    best_tau_overall_acc = 0
 
    fixed_tau_best_accs = [0,0,0,0,0,0,0]
    cosine_tau_best_accs = [0,0,0,0,0,0,0]

    for i in fixed_tau_list:
        fixed_exp_avgs.append(netC.state_dict())
        cosine_exp_avgs.append(netC.state_dict())

    for epoch in range(opt.niter):
        num_greater_thresh = 0
        count_class = [0]*10
        count_class_less = [0]*opt.num_classes
        count_class_hist = [0]*opt.num_classes
        count_class_less_hist = [0]*opt.num_classes
        classification_loss_sum = 0
        errD_real_sum = 0
        errD_fake_sum = 0
        errD_sum = 0
        errG_sum = 0
        errG_adv_sum = 0
        student_ce_sum = 0
        wa_ce_sum = 0
        data_size = 0 
        accD_real_sum = 0
        accD_fake_sum = 0
        accG_sum = 0
        accD_sum = 0
        div_loss_sum = 0
        total=0
        correct=0

        iter_proxy = iter(trainloader_proxy)

        if opt.diverse==True:
            netG.eval()
            if epoch!=0:
                num_samples_per_batch = 250
                for idx in range(int(num_samples_per_batch/gen_batch_size)):
                    noise_test = torch.randn(gen_batch_size, nz, 1, 1, device=device)
                    imgs = netG(noise_test)
                    diverse_images[(epoch*num_samples_per_batch+idx*gen_batch_size) : (epoch*num_samples_per_batch+idx*gen_batch_size + gen_batch_size)] = imgs.detach().cpu()

                target_arr = torch.zeros((len(diverse_images)))
                for i in range(len(diverse_images)):
                    inputs = torch.reshape(diverse_images[i], (1,3,32,32))
                    teacher_outputs = teacher_net(inputs)
                    teacher_outputs = teacher_outputs.detach()
                    _, teacher_predicted = teacher_outputs.max(1)
                    target_arr[i] = teacher_predicted.item()

                gen_set = GeneratedDataset(data = diverse_images, targets = target_arr, transform=transform_train)

            trainloader1 = torch.utils.data.DataLoader(
                gen_set, batch_size=opt.batchSize, shuffle=True, num_workers=2)
                
            iter_diverse = iter(trainloader1)

        for i, data in enumerate(dataloader, 0):
        #for i in range(0,100):

            real_cpu = data[0].to(device)
            batch_size = real_cpu.size(0)
            if batch_size==0:
                continue
            data_size = data_size + batch_size

            noise_data = torch.randn(batch_size, nz, 1, 1, device=device)
            
            # one iteration of current images  
            netG.train()
            netG.zero_grad()
            
            gen_images = netG(noise_data)

            if opt.auto_augment==True:
                imgs = (gen_images * 0.5 + 0.5)
                for im in range(len(imgs)):
                    imgs[im] = pil_transform(imgs[im])
            else:
                imgs = gen_images 

            imgs = imgs.detach()
            teacher_net.eval()
            netC.train()
            optimizer_student.zero_grad()
            #print(gen_images.shape)

            teacher_outputs = teacher_net(imgs)
            teacher_outputs = teacher_outputs.detach()
            _, teacher_predicted = teacher_outputs.max(1)
            #print(teacher_predicted.shape)

            student_outputs = netC(imgs)
            _, student_predicted = student_outputs.max(1)
            loss_student = criterion_student(student_outputs, teacher_predicted)

            loss_student.backward()
            optimizer_student.step()
            
            total += teacher_predicted.size(0)
            correct += student_predicted.eq(teacher_predicted).sum().item()

            # 2 iterations of old images 
            if opt.diverse==True:
                optimizer_student.zero_grad()
                #print(gen_images.shape)
                inputs1, targets1 = iter_diverse.next()
                inputs1, targets1 = inputs1.to(device), targets1.to(device)

                targets1 = targets1.type(torch.cuda.LongTensor)
                student_outputs = netC(inputs1)
                _, student_predicted = student_outputs.max(1)
                loss_student = criterion_student(student_outputs, targets1)

                loss_student.backward()
                optimizer_student.step()

                total += targets1.size(0)
                correct += student_predicted.eq(targets1).sum().item()
            
            if opt.use_proxy_data==True and i % opt.use_proxy_frequency==0:
                optimizer_student.zero_grad()
                inputs1, targets1 = iter_proxy.next()
                inputs1, targets1 = inputs1.to(device), targets1.to(device)

                targets1 = targets1.type(torch.cuda.LongTensor)
                student_outputs = netC(inputs1)
                _, student_predicted = student_outputs.max(1)
                loss_student = criterion_student(student_outputs, targets1)

                loss_student.backward()
                optimizer_student.step() 

            for tau, new_state_dict in zip(fixed_tau_list, fixed_exp_avgs):
                for key,value in netC.state_dict().items():
                    new_state_dict[key] = (1-tau)*value + tau*new_state_dict[key] 

            for tau, new_state_dict in zip(cosine_tau_list, cosine_exp_avgs):
                for key,value in netC.state_dict().items():
                    new_state_dict[key] = (1-tau)*value + tau*new_state_dict[key]
            
            best_index = 0
            best_tau_degan_acc = 0
            for t in range(len(fixed_tau_list)):
                if best_tau_degan_acc < fixed_tau_best_accs[t]:
                    best_tau_degan_acc = fixed_tau_best_accs[t]
                    best_index = t

            if opt.network=='resnet':
                best_model_tau = ResNet18(opt.num_classes)
            else:
                if opt.wo_batch_norm==True:
                    best_model_tau = AlexNet_half_wo_BN()
                else:
                    best_model_tau = AlexNet_half()
            best_model_tau.load_state_dict(fixed_exp_avgs[best_index])
            best_model_tau = best_model_tau.to(device)
            best_model_tau.eval()

            ############################
            # (2) Update G network: maximize log(D(G(z)))
            ###########################
            if not opt.disable_dis:
                netD.train()
            #netG.zero_grad()
            netC.eval()

            #netG.zero_grad()
            #imgs = netG(noise_data)
            fake = gen_images
            if opt.use_wa_student_div_loss==True:
                fake_class = best_model_tau(fake)
            else:
                fake_class = netC(fake)
            #fake = gen_images.detach()
            #print(fake.shape, noise.shape)

            temp = opt.temp
            sm_fake_class = F.softmax(fake_class/temp, dim=1)
            sm_fake_class_entr = F.softmax(fake_class, dim=1)
            #fake_class = student_outputs
            #sm_fake_class = F.softmax(student_outputs, dim=1)

            #print(sm_fake_class)
            class_max = fake_class.max(1,keepdim=True)[0]
            class_argmax = fake_class.max(1,keepdim=True)[1]

            # Classification loss
            classification_loss = torch.mean(torch.sum(-sm_fake_class_entr*torch.log(sm_fake_class_entr+1e-5),dim=1))
            classification_loss_add = torch.sum(-sm_fake_class_entr*torch.log(sm_fake_class_entr+1e-5))
            classification_loss_sum = classification_loss_sum + (classification_loss_add).cpu().data.numpy()

            sm_batch_mean = torch.mean(sm_fake_class,dim=0)
            div_loss = torch.sum(sm_batch_mean*torch.log(sm_batch_mean+1e-5)) # Maximize entropy across batch
            div_loss_sum = div_loss_sum + div_loss.item()*batch_size



            label = torch.full((fake.shape[0],), real_label, device=device)
            label = label.type(torch.cuda.FloatTensor)
            label.fill_(real_label)  # fake labels are real for generator cost
            #if opt.use_ce_loss==True:
            #    fake = imgs
            if not opt.disable_dis:
                output = netD(fake)
            c_l = opt.c_l # 0 # Hyperparameter to weigh entropy loss
            d_l = opt.d_l # 500 # Hyperparameter to weigh the diversity loss
            if not opt.disable_dis:
                errG_adv = criterion(output, label)
            else:
                errG_adv = 0
            if not opt.disable_dis:
                errG_adv_sum = errG_adv_sum + (criterion_sum(output, label)).cpu().data.numpy()

                accG = (label[output>0.5]).shape[0]
                accG_sum = accG_sum + float(accG)

            errG = errG_adv + c_l * classification_loss + d_l * div_loss
            errG_sum = errG_adv_sum + c_l * classification_loss_sum + d_l * div_loss_sum

            if opt.use_ce_loss==True:
                loss_student = criterion_student(fake_class, teacher_predicted)
                ce_l = opt.ce_l
                student_ce_sum = student_ce_sum + (criterion_student_sum(fake_class, teacher_predicted)).cpu().data.numpy()
                errG = errG - ce_l * loss_student
                errG_sum = errG_sum - ce_l * student_ce_sum
                
            if opt.use_wa_student_ce_loss==True:
                WA_output = best_model_tau(fake)
                loss_wa = criterion_student(WA_output, teacher_predicted)
                ce_l = opt.ce_l
                errG = errG - ce_l * loss_wa
                wa_ce_sum = wa_ce_sum + (criterion_student_sum(WA_output, teacher_predicted)).cpu().data.numpy()
                errG_sum = errG_sum - ce_l * wa_ce_sum

            if opt.use_KL_wa_loss==True:
                k_l = opt.k_l
                #errG = errG - k_l *  criterion_kl(F.log_softmax(WA_output, dim=1), F.softmax(loss_student, dim=1))
                errG = errG - k_l *  nn.KLDivLoss(reduction='sum')(F.log_softmax(WA_output, dim=1),F.softmax(fake_class, dim=1))
            
            errG.backward()
            if not opt.disable_dis:
                D_G_z2 = output.mean().item()
            optimizerG.step() 


            ############################
            # (1) Update D network: maximize log(D(x)) + log(1 - D(G(z)))
            ###########################
            # train with real
            if not opt.disable_dis:
                netD.zero_grad()
            
            label = torch.full((batch_size,), real_label, device=device)
            label = label.type(torch.cuda.FloatTensor)
           
            if not opt.disable_dis:
                output = netD(real_cpu)

                errD_real = criterion(output, label)
                errD_real_sum = errD_real_sum + (criterion_sum(output,label)).cpu().data.numpy()

                accD_real = (label[output>0.5]).shape[0]
                accD_real_sum = accD_real_sum + float(accD_real)

                errD_real.backward()
            
                D_x = output.mean().item()

            
                label.fill_(fake_label)
                output = netD(fake.detach())

                #print(fake, output)
                errD_fake = criterion(output, label)
                errD_fake_sum = errD_fake_sum + (criterion_sum(output, label)).cpu().data.numpy()

                accD_fake = (label[output<=0.5]).shape[0]
                accD_fake_sum = accD_fake_sum + float(accD_fake)

                errD_fake.backward()
                D_G_z1 = output.mean().item()

                errD = errD_real + errD_fake
                errD_sum = errD_real_sum + errD_fake_sum

                accD = accD_real + accD_fake
                accD_sum = accD_real_sum + accD_fake_sum

                optimizerD.step()


            """ 
            if not opt.disable_dis:
                print('[%d/%d][%d/%d] Loss_D: %.4f Loss_G: %.4f D(x): %.4f D(G(z)): %.4f / %.4f'
                  % (epoch, opt.niter, i, len(dataloader),
                     errD.item(), errG.item(), D_x, D_G_z1, D_G_z2))
            else:
                print('[%d/%d][%d/%d] Loss_G: %.4f '
                  % (epoch, opt.niter, i, len(dataloader),
                     errG.item()))
            """
            pred_class = F.softmax(fake_class,dim=1).max(1, keepdim=True)[0]
            pred_class_argmax = F.softmax(fake_class,dim=1).max(1, keepdim=True)[1]
            num_greater_thresh = num_greater_thresh + (torch.sum(pred_class > 0.9).cpu().data.numpy())
            for argmax, val in zip(pred_class_argmax, pred_class):
                if val > 0.9:
                    count_class_hist.append(argmax)
                    count_class[argmax] = count_class[argmax] + 1
                else:
                    count_class_less_hist.append(argmax)
                    count_class_less[argmax] = count_class_less[argmax] + 1

            if i % 100 == 0:
                #tf.summary.image("Gen Imgs Training", (fake+1)/2, epoch)
                grid = torchvision.utils.make_grid((fake+1)/2)
                writer.add_image("Gen Imgs Training", grid, epoch)
       
        # print train acc of student 
        print("Epoch : ", epoch)
        print("Learning rate : ", scheduler_student.get_lr())
        print("Student train acc : ", 100.*correct/total, "loss student = ", loss_student.item())
        train_accs.append(100.*correct/total)
        # measure test acc on cifar-10
        netC.eval()
        correct_test = 0
        total_test = 0
        with torch.no_grad():
            for batch_idx, (inputs, targets) in enumerate(testloader):
                inputs, targets = inputs.to(device), targets.to(device)
                outputs = netC(inputs)

                _, predicted = outputs.max(1)
                total_test += targets.size(0)
                correct_test += predicted.eq(targets).sum().item()

        print("Test Acc on cifar-10 : ", 100.*correct_test/total_test, get_model_accuracy(netC, testloader))
        test_accs.append(100.*correct_test/total_test)

        nb_classes = opt.num_classes
        confusion_matrix = torch.zeros(nb_classes, nb_classes)
        with torch.no_grad():
            for batch_idx, (inputs, targets) in enumerate(val_dcgan_loader):
                inputs, targets = inputs.to(device), targets.to(device)
                outputs = netC(inputs)
                _, preds = torch.max(outputs, 1)
                for t, p in zip(targets.view(-1), preds.view(-1)):
                    confusion_matrix[t.long(), p.long()] += 1

        conf_num = confusion_matrix.diag()/confusion_matrix.sum(1)
        conf_mat = conf_num.cpu().detach().numpy()
        conf_mat = conf_mat[~np.isnan(conf_mat)]
        dcgan_acc = np.mean(conf_mat)*100
        print("Dcgan Val acc : ", dcgan_acc)
        dcgan_val_accs.append(dcgan_acc)
        if best_dcgan_acc < dcgan_acc:
           best_dcgan_acc = dcgan_acc
           print("Best dcgan acc reached")


        nb_classes = opt.num_classes
        confusion_matrix = torch.zeros(nb_classes, nb_classes)
        with torch.no_grad():
            for batch_idx, (inputs, targets) in enumerate(val_degan_loader):
                inputs, targets = inputs.to(device), targets.to(device)
                outputs = netC(inputs)
                _, preds = torch.max(outputs, 1)
                for t, p in zip(targets.view(-1), preds.view(-1)):
                    confusion_matrix[t.long(), p.long()] += 1

        conf_num = confusion_matrix.diag()/confusion_matrix.sum(1)
        conf_mat = conf_num.cpu().detach().numpy()
        conf_mat = conf_mat[~np.isnan(conf_mat)]
        degan_acc = np.mean(conf_mat)*100
        print("Degan Val acc : ", degan_acc)
        degan_val_accs.append(degan_acc)
        save_ep = find_epoch_num(epoch)

        if best_degan_acc < degan_acc:
            best_degan_acc = degan_acc
            print("Best degan acc reached")
            state_ = {
                'net': netC.state_dict(),
                'acc': degan_acc,
                'epoch': epoch,
            }
            if opt.warmup==True:
                if opt.diverse==True:
                    torch.save(state_, '%s/best_netC_diverse_%.4f_%s_ep_%s.pth' % (opt.outf, inital_lr, opt.name, save_ep))
                    print('%s/best_netC_diverse_%.4f_%s_ep_%s.pth' % (opt.outf, inital_lr, opt.name, save_ep))
                else:
                    torch.save(state_, '%s/best_netC_%.4f_%s_ep_%s.pth' % (opt.outf, inital_lr, opt.name, save_ep))
                    print('%s/best_netC_%.4f_%s_ep_%s.pth' % (opt.outf, inital_lr, opt.name, save_ep))
            else:
                torch.save(state_, '%s/best_netC_%s_ep_%s.pth' % (opt.outf, opt.name, save_ep))
                print('%s/best_netC_%s_ep_%s.pth' % (opt.outf, opt.name, save_ep))
            
            # find the best tau model and save it
            idx_count = 0
            for tau, new_state_dict in zip(fixed_tau_list, fixed_exp_avgs):
                nb_classes = 10
                confusion_matrix = torch.zeros(nb_classes, nb_classes)
                if opt.network=='resnet':
                    evaluation_netC = ResNet18()
                else:
                    if opt.wo_batch_norm==True:
                        evaluation_netC = AlexNet_half_wo_BN()
                    else:
                        evaluation_netC = AlexNet_half()
                evaluation_netC.load_state_dict(new_state_dict)
                evaluation_netC = evaluation_netC.to(device)
                evaluation_netC.eval()
                with torch.no_grad():
                    for batch_idx, (inputs, targets) in enumerate(val_degan_loader):
                        inputs, targets = inputs.to(device), targets.to(device)
                        outputs = evaluation_netC(inputs)
                        _, preds = torch.max(outputs, 1)
                        for t, p in zip(targets.view(-1), preds.view(-1)):
                            confusion_matrix[t.long(), p.long()] += 1

                conf_num = confusion_matrix.diag()/confusion_matrix.sum(1)
                conf_mat = conf_num.cpu().detach().numpy()
                conf_mat = conf_mat[~np.isnan(conf_mat)]
                degan_acc_tau = np.mean(conf_mat)*100
                if fixed_tau_best_accs[idx_count] < degan_acc_tau:
                    fixed_tau_best_accs[idx_count] = degan_acc_tau
                idx_count += 1
            
            best_index = 0
            best_tau_degan_acc = 0
            for t in range(len(fixed_tau_list)):
                if best_tau_degan_acc < fixed_tau_best_accs[t]:
                    best_tau_degan_acc = fixed_tau_best_accs[t]
                    best_index = t
            
            if best_tau_overall_acc < fixed_tau_best_accs[best_index]:
                best_tau_overall_acc = fixed_tau_best_accs[best_index]
                if opt.network=='resnet':
                    best_model_tau = ResNet18(opt.num_classes)
                else: 
                    if opt.wo_batch_norm==True:
                        best_model_tau = AlexNet_half_wo_BN()
                    else:
                        best_model_tau = AlexNet_half()   
                best_model_tau.load_state_dict(fixed_exp_avgs[best_index])
                best_model_tau = best_model_tau.to(device)
                best_model_tau.eval()
                total_test = 0
                correct_test = 0
                with torch.no_grad():
                    for batch_idx, (inputs, targets) in enumerate(testloader):
                        inputs, targets = inputs.to(device), targets.to(device)
                        outputs = best_model_tau(inputs)
                        _, predicted = outputs.max(1)
                        total_test += targets.size(0)
                        correct_test += predicted.eq(targets).sum().item()

                print("Test Acc on cifar-10 for best model of tau: ", best_index, best_tau_degan_acc, 100.*correct_test/total_test, get_model_accuracy(best_model_tau, testloader))
                state_1 = {
                        'net': best_model_tau.state_dict(),
                        'acc': 100.*correct_test/total_test,
                        'epoch': epoch,
                    }
                torch.save(state_1, '%s/best_tau_model_%s_ep_%s.pth' % (opt.outf, opt.name, save_ep))
                print('%s/best_tau_model_%s_ep_%s.pth' % (opt.outf, opt.name, save_ep))
 
        correct_teacher = 0
        total_teacher = 0
        with torch.no_grad():
            for batch_idx, (inputs, targets) in enumerate(trainloader_proxy):
                inputs, targets = inputs.to(device), targets.to(device)
                outputs = netC(inputs)
                _, predicted = outputs.max(1)
                total_teacher += targets.size(0)
                correct_teacher += predicted.eq(targets).sum().item()

        print("Student Teacher agreement on proxy data : ", 100.*correct_teacher/total_teacher)
        agg = 100.*correct_teacher/total_teacher
        acc = 100.*correct_test/total_test
        agg_accs.append(agg)
        if agg> best_agg:
            best_agg = agg
            print("Best Student Teacher Agg Acc : ", best_agg, " at test acc = ", acc)
 
        if acc > best_acc:
            best_acc = acc
            print("Best Test Acc : ", opt.warmup, opt.diverse, inital_lr, best_acc)
            print()

        

        """
        idx_count = 0
        for tau, new_state_dict in zip(cosine_tau_list, cosine_exp_avgs):
            nb_classes = 10
            confusion_matrix = torch.zeros(nb_classes, nb_classes)
            evaluation_netC = AlexNet_half()
            evaluation_netC.load_state_dict(new_state_dict)
            evaluation_netC = evaluation_netC.to(device)
            evaluation_netC.eval()
            with torch.no_grad():
                for batch_idx, (inputs, targets) in enumerate(val_degan_loader):
                    inputs, targets = inputs.to(device), targets.to(device)
                    outputs = evaluation_netC(inputs)
                    _, preds = torch.max(outputs, 1)
                    for t, p in zip(targets.view(-1), preds.view(-1)):
                        confusion_matrix[t.long(), p.long()] += 1

            degan_acc_tau = torch.mean(confusion_matrix.diag()/confusion_matrix.sum(1)).item()*100.
            if cosine_tau_best_accs[idx_count] < degan_acc_tau:
                cosine_tau_best_accs[idx_count] = degan_acc_tau
            state_1 = {
                'net': evaluation_netC.state_dict(),
                'acc': degan_acc_tau,
                'epoch': epoch,
            }
            torch.save(state_1, "tau_student_models/"+ str(opt.name) + "/cosine_tau_"+str(tau)+"_epoch_"+str(epoch)+'.pth')
            torch.save(new_state_dict,"tau_student_models/"+ str(opt.name) + "/cosine_tau_"+str(tau)+"_epoch_"+str(epoch)+'.pkl')
            idx_count+=1
        """
        for va in range(len(cosine_tau_list)):
            cosine_tau_list[va] = adjust_momentum(epoch, cosine_tau_list[va], opt.niter)
        
        print(fixed_tau_list ) #[0,0.5,0.9,0.99,0.999,0.9995,0.9998]
        print(fixed_tau_best_accs)
        print(cosine_tau_list) # [0,0.5,0.9,0.99,0.999,0.9995,0.9998]
        print(cosine_tau_best_accs)
        print()
        print()

        scheduler_student.step()
        if opt.warmup==True and epoch<10:
            for param_group in optimizer_student.param_groups:
                param_group["lr"] = inital_lr * epoch
        # do checkpointing
        if epoch%10==0:
            torch.save(netG.state_dict(), '%s/netG_epoch_%d.pth' % (opt.outf, epoch))
            if not opt.disable_dis:
                torch.save(netD.state_dict(), '%s/netD_epoch_%d.pth' % (opt.outf, epoch))  

        # Generate fake samples for visualization

        test_size = 100
        noise_test = torch.randn(test_size, nz, 1, 1, device=device)
        fake_test = netG(noise_test)
        fake_test_class = netC(fake_test)
        pred_test_class_max = F.softmax(fake_test_class,dim=1).max(1, keepdim=True)[0]
        pred_test_class_argmax = F.softmax(fake_test_class,dim=1).max(1, keepdim=True)[1]

        """ 
        for i in range(10):
            print("Score>0.9: Class",i,":",torch.sum(((pred_test_class_argmax.view(test_size)==i) & (pred_test_class_max.view(test_size)>0.9)).float()))
            print("Score<0.9: Class",i,":",torch.sum(((pred_test_class_argmax.view(test_size)==i) & (pred_test_class_max.view(test_size)<0.9)).float()))
        """
        if fake_test[pred_test_class_argmax.view(test_size)==0].shape[0] > 0:
            grid = torchvision.utils.make_grid((fake_test[pred_test_class_argmax.view(test_size)==0]+1)/2)
            writer.add_image("Gen Imgs Test: Airplane", grid, epoch)

        if fake_test[pred_test_class_argmax.view(test_size)==1].shape[0] > 0:
            grid = torchvision.utils.make_grid((fake_test[pred_test_class_argmax.view(test_size)==1]+1)/2)
            writer.add_image("Gen Imgs Test: Automobile", grid, epoch)

        if fake_test[pred_test_class_argmax.view(test_size)==2].shape[0] > 0:
            grid = torchvision.utils.make_grid((fake_test[pred_test_class_argmax.view(test_size)==2]+1)/2)
            writer.add_image("Gen Imgs Test: Bird", grid, epoch)

        if fake_test[pred_test_class_argmax.view(test_size)==3].shape[0] > 0:
            grid = torchvision.utils.make_grid((fake_test[pred_test_class_argmax.view(test_size)==3]+1)/2)
            writer.add_image("Gen Imgs Test: Cat", grid, epoch)

        if fake_test[pred_test_class_argmax.view(test_size)==4].shape[0] > 0:
            grid = torchvision.utils.make_grid((fake_test[pred_test_class_argmax.view(test_size)==4]+1)/2)
            writer.add_image("Gen Imgs Test: Deer", grid, epoch)

        if fake_test[pred_test_class_argmax.view(test_size)==5].shape[0] > 0:
            grid = torchvision.utils.make_grid((fake_test[pred_test_class_argmax.view(test_size)==5]+1)/2)
            writer.add_image("Gen Imgs Test: Dog", grid, epoch)

        if fake_test[pred_test_class_argmax.view(test_size)==6].shape[0] > 0:
            grid = torchvision.utils.make_grid((fake_test[pred_test_class_argmax.view(test_size)==6]+1)/2)
            writer.add_image("Gen Imgs Test: Frog", grid, epoch)

        if fake_test[pred_test_class_argmax.view(test_size)==7].shape[0] > 0:
            grid = torchvision.utils.make_grid((fake_test[pred_test_class_argmax.view(test_size)==7]+1)/2)
            writer.add_image("Gen Imgs Test: Horse", grid, epoch)

        if fake_test[pred_test_class_argmax.view(test_size)==8].shape[0] > 0:
            grid = torchvision.utils.make_grid((fake_test[pred_test_class_argmax.view(test_size)==8]+1)/2)
            writer.add_image("Gen Imgs Test: Ship", grid, epoch)

        if fake_test[pred_test_class_argmax.view(test_size)==9].shape[0] > 0:
            grid = torchvision.utils.make_grid((fake_test[pred_test_class_argmax.view(test_size)==9]+1)/2)
            writer.add_image("Gen Imgs Test: Truck", grid, epoch)
       
        """
        print(count_class , "Above  0.9")
        print(count_class_less, "Below 0.9")
        """
        writer.add_histogram("above 0.9", np.asarray(count_class), epoch, bins=10)
        writer.add_histogram("above 0.9", np.asarray(count_class), epoch, bins=10)
        threshold.append(num_greater_thresh)
        
        writer.add_scalar("1 Train Discriminator accuracy(all)", accD_sum/ (2*data_size), epoch)
        writer.add_scalar("2 Train Discriminator accuracy(fake)", accD_fake_sum/ data_size, epoch)
        writer.add_scalar("3 Train Discriminator accuracy(real)", accD_real_sum/ data_size, epoch)
        writer.add_scalar("4 Train Generator accuracy(fake)", accG_sum/ data_size, epoch)
        writer.add_scalar("5 Train Discriminator loss (real)", errD_real_sum/ data_size, epoch)
        writer.add_scalar("6 Train Discriminator loss (fake)", errD_fake_sum/ data_size, epoch)
        writer.add_scalar("7 Train Discriminator loss (all)", errD_sum/(2* data_size), epoch)
        writer.add_scalar("8 Train Generator loss (adv)", errG_adv_sum/ data_size, epoch)
        writer.add_scalar("9 Train Generator loss (classification)", classification_loss_sum/ data_size, epoch)
        writer.add_scalar("10 Train Generator loss (diversity)", div_loss_sum/ data_size, epoch)
        writer.add_scalar("11 Train Generator loss (all)", errG_sum/ data_size, epoch)
        writer.add_scalar("12 Student Teacher Agreement ", agg, epoch)
        writer.add_scalar("13 Cifar-10 Test Accuracy ", acc, epoch)

        writer.export_scalars_to_json("./all_scalars.json")
   
        """ 
        if epoch%50==0:
            for img_num in range(50000):
                test_size = 1
                noise_test = torch.randn(test_size, nz, 1, 1, device=device)
                img = netG(noise_test)
                #print(img.shape)

                img = img[0].detach().cpu()
                img = img / 2 + 0.5   # unnormalize
                npimg = img.numpy()   # convert from tensor
                np_img = np.transpose(npimg, (1, 2, 0))

                np_img = np_img*255
                np_img = np_img.astype(np.uint8)
                #print(x, np.max(x), np.min(x))
                im = Image.fromarray(np_img)
                im.save("./SVHN/svhn_generated_images/file_" + str(img_num)+ ".png")

        """
    print("Best Test Acc on cifar-10 test data = ", best_acc)
    print("Best Student-teacher agreement on proxy data = ", best_agg)
    print("Best dcgan val acc = ", best_dcgan_acc)
    print("Best degan val acc = ", best_degan_acc)

    print("Best tau list : ")
    print(fixed_tau_list ) #[0,0.5,0.9,0.99,0.999,0.9995,0.9998]
    print(fixed_tau_best_accs)
    print(cosine_tau_list) # [0,0.5,0.9,0.99,0.999,0.9995,0.9998]
    print(cosine_tau_best_accs)

    
    best_index = 0
    best_tau_degan_acc = 0
    for t in range(len(fixed_tau_list)):
        if best_tau_degan_acc < fixed_tau_best_accs[t]:
            best_tau_degan_acc = fixed_tau_best_accs[t]
            best_index = t

    if opt.network=='resnet':
        best_model_tau = ResNet18(opt.num_classes)
    else:
        if opt.wo_batch_norm==True:
            best_model_tau = AlexNet_half_wo_BN()
        else:
            best_model_tau = AlexNet_half()    
    best_model_tau.load_state_dict(fixed_exp_avgs[best_index])
    best_model_tau = best_model_tau.to(device)
    best_model_tau.eval()
    total_test = 0
    correct_test = 0
    with torch.no_grad():
        for batch_idx, (inputs, targets) in enumerate(testloader):
            inputs, targets = inputs.to(device), targets.to(device)
            outputs = best_model_tau(inputs)
            _, predicted = outputs.max(1)
            total_test += targets.size(0)
            correct_test += predicted.eq(targets).sum().item()

        print("Test Acc on cifar-10 for best model of tau: ", t, best_tau_degan_acc, 100.*correct_test/total_test, get_model_accuracy(best_model_tau, testloader))
    state_1 = {
                'net': best_model_tau.state_dict(),
                'acc': 100.*correct_test/total_test,
                'epoch': epoch,
            }
    torch.save(state_1, '%s/last_epoch_tau_model_%s_ep_%s.pth' % (opt.outf, opt.name, save_ep))
    print('%s/last_epoch_tau_model_%s_ep_%s.pth' % (opt.outf, opt.name, save_ep))
    
    """
    best_index = 0
    best_tau_degan_acc = 0
    for t in range(len(cosine_tau_list)):
        if best_tau_degan_acc < cosine_tau_best_accs[t]:
            best_tau_degan_acc = cosine_tau_best_accs[t]
            best_index = t

    best_model_tau = AlexNet_half()
    best_model_tau.load_state_dict(cosine_exp_avgs[best_index])
    best_model_tau = best_model_tau.to(device)
    best_model_tau.eval()
    total_test = 0
    correct_test = 0
    with torch.no_grad():
        for batch_idx, (inputs, targets) in enumerate(testloader):
            inputs, targets = inputs.to(device), targets.to(device)
            outputs = best_model_tau(inputs)
            _, predicted = outputs.max(1)
            total_test += targets.size(0)
            correct_test += predicted.eq(targets).sum().item()

        print("Test Acc on cifar-10 for best model of tau: ", t, best_tau_degan_acc, 100.*correct_test/total_test)
    state_1 = {
                'net': best_model_tau.state_dict(),
                'acc': 100.*correct_test/total_test,
                'epoch': epoch,
            }
    torch.save(state_1, "tau_student_models/"+ str(opt.name) + "/best_cosine_tau_model.pth")
    torch.save(best_model_tau,"tau_student_models/"+ str(opt.name) + "/best_cosine_tau_model.pkl")

    """
    """    
    with open('train_accs_altr_gan' + str(opt.name) + '.pkl','wb') as f:
        pickle.dump(train_accs, f)

    with open('dcgan_val_accs_altr_gan' + str(opt.name) + ' .pkl','wb') as f:
        pickle.dump(dcgan_val_accs, f)

    with open('degan_val_accs_altr_gan' + str(opt.name) + ' .pkl','wb') as f:
        pickle.dump(degan_val_accs, f)

    with open('agg_accs_altr_gan' + str(opt.name) + ' .pkl','wb') as f:
        pickle.dump(agg_accs, f)

    with open('test_accs_altr_gan' + str(opt.name) + ' .pkl','wb') as f:
        pickle.dump(test_accs, f)
    """
writer.close()


